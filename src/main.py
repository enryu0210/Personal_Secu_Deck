import customtkinter as ctk
import os
import threading
import time
import queue
import tempfile
import math
import json
import re
import subprocess
from pathlib import Path
from tkinterdnd2 import TkinterDnD
from datetime import datetime
from tkinter import messagebox
from tkinter import filedialog
from startup_checker import StartupMonitor
from Cleaner import scan_dormant_files, summarize, delete_files, human_size, DormantFile, CleanerScanner, classify_delete_safety
from scanner import SensitiveDataScanner
from secure_wiper import SecureWiper

# --- 유틸 영역 ---
def parse_dnd_files(data: str) -> list[str]:
    """TkDND event.data 문자열에서 파일/폴더 경로들을 파싱."""
    if not data:
        return []
    s = data.strip()

    # { ... }로 감싸진 케이스(공백 포함 경로)
    if "{" in s and "}" in s:
        items = re.findall(r"\{([^}]*)\}", s)
        files = [it.strip() for it in items if it.strip()]
    else:
        # 공백으로 분리되는 케이스(공백 없는 경로들)
        files = [it.strip() for it in s.split() if it.strip()]

    # 정규화
    out = []
    for f in files:
        f = f.replace("\\", "/")
        out.append(f)
    return out


def bind_drop_files(widget, on_files) -> bool:
    """
    widget에 파일 드롭을 바인딩.
    on_files: (list[str]) -> None
    """
    if not hasattr(widget, "drop_target_register") or not hasattr(widget, "dnd_bind"):
        return False

    try:
        try:
            from tkinterdnd2 import DND_FILES
        except Exception:
            DND_FILES = "DND_Files"

        widget.drop_target_register(DND_FILES)

        def _on_drop(event):
            files = parse_dnd_files(getattr(event, "data", ""))
            if files:
                on_files(files)

        widget.dnd_bind("<<Drop>>", _on_drop)
        return True
    except Exception:
        return False

def get_media_type_for_path(path: str) -> str:
    try:
        # 1. 경로 절대경로로 변환 및 드라이브 문자 추출 (예: "C")
        abs_path = os.path.abspath(path)
        drive_root = os.path.splitdrive(abs_path)[0] # "C:"
        drive_letter = drive_root.replace(":", "").upper()

        if not drive_letter:
            return "UNKNOWN"

        # 2. PowerShell 명령어 (에러 발생 시 JSON 파싱 에러 방지를 위해 try-catch 내장)
        # Get-Partition -> Get-Disk -> MediaType 확인
        ps_command = f"""
        try {{
            $p = Get-Partition -DriveLetter {drive_letter} -ErrorAction Stop
            $d = Get-Disk -Number $p.DiskNumber -ErrorAction Stop
            $type = $d.MediaType
            if (-not $type) {{ $type = "Unspecified" }}
            @{{type=$type.ToString()}} | ConvertTo-Json -Compress
        }} catch {{
            @{{type="ERROR"}} | ConvertTo-Json -Compress
        }}
        """

        # 3. 서브프로세스 실행 (콘솔 창 안 뜨게 설정)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", ps_command],
            text=True,
            startupinfo=startupinfo  # 검은색 팝업창 방지
        ).strip()

        # 4. JSON 파싱 및 결과 판단
        try:
            data = json.loads(output)
            media_type = data.get("type", "").upper()
        except json.JSONDecodeError:
            media_type = "ERROR"

        # 5. 결과 매핑
        if "SSD" in media_type:
            return "SSD"
        elif "HDD" in media_type:
            return "HDD"
        else:
            # USB나 가상 드라이브 등 판별 불가 시
            # C드라이브는 요즘 99% SSD이므로 SSD로 추정
            if drive_letter == "C":
                return "SSD"
            # 나머지는 안전하게(강력하게) 지우기 위해 HDD로 간주
            return "HDD" 

    except Exception as e:
        print(f"디스크 판별 오류: {e}")
        # 에러 나면 안전하게 HDD 방식(3-pass) 적용
        return "HDD"


def summarize_media_types(paths: list[str]) -> dict:
    """
    paths를 SSD/HDD/UNKNOWN으로 분류해서 요약 반환
    return 예:
    {
      "SSD": ["C:\\a.txt", ...],
      "HDD": ["D:\\b.txt", ...],
      "UNKNOWN": ["E:\\c.txt", ...],
    }
    """
    buckets = {"SSD": [], "HDD": [], "UNKNOWN": []}
    for p in paths:
        mt = get_media_type_for_path(p)
        if mt not in buckets:
            mt = "UNKNOWN"
        buckets[mt].append(p)
    return buckets

def build_wipe_confirm_message(paths: list[str]) -> str:
    b = summarize_media_types(paths)
    ssd_n = len(b["SSD"])
    hdd_n = len(b["HDD"])
    unk_n = len(b["UNKNOWN"])
    total = len(paths)

    lines = []
    lines.append("⚠️ 이 작업은 되돌릴 수 없습니다.\n")
    lines.append(f"선택 항목: {total}개\n")

    # SSD/HDD 안내 문구
    if total == 1:
        # 단일 선택이면 더 직관적으로
        if ssd_n == 1:
            lines.append("• 저장장치: SSD 감지\n")
            lines.append("• 방식: 1-pass overwrite (NIST SP 800-88) 후 삭제\n")
        elif hdd_n == 1 or unk_n == 1:
            # UNKNOWN은 보수적으로 HDD 방식으로 안내
            lines.append(f"• 저장장치: {'HDD 감지' if hdd_n == 1 else '판별 불가(보수 적용)'}\n")
            lines.append("• 방식: 3-pass overwrite (DoD 5220.22-M) 후 삭제\n")
    else:
        # 여러 개면 요약
        lines.append("• 파일 위치별 적용 방식:\n")
        if ssd_n:
            lines.append(f"   - SSD: {ssd_n}개 → 1-pass overwrite (NIST SP 800-88)\n")
        if hdd_n:
            lines.append(f"   - HDD: {hdd_n}개 → 3-pass overwrite (DoD 5220.22-M)\n")
        if unk_n:
            lines.append(f"   - 판별 불가: {unk_n}개 → 안전을 위해 HDD 방식(3-pass) 적용\n")

    lines.append("\n진행하시겠습니까?")
    return "".join(lines)

# --- 초기 설정 ---
# ctk.set_appearance_mode("Dark")
# ctk.set_default_color_theme("blue")


class App(TkinterDnD.Tk):
    def __init__(self):
        super().__init__()

        # ✅ Tk 루트 흰색 비침 방지: 전체 덮는 CTk 배경 레이어
        self.bg_layer = ctk.CTkFrame(self, corner_radius=0, fg_color=("#F3F3F3", "#111111"))
        self.bg_layer.pack(fill="both", expand=True)

        # 1. 윈도우 설정
        self.title("AI Security Guardian")
        self.geometry("900x650")
        self.resizable(False, False)

        # 폰트 설정
        self.font_title = ctk.CTkFont(family="Malgun Gothic", size=26, weight="bold")
        self.font_subtitle = ctk.CTkFont(family="Malgun Gothic", size=18, weight="bold")
        self.font_body = ctk.CTkFont(family="Malgun Gothic", size=14)
        self.font_bold = ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold")

        # 2. 그리드 레이아웃
        self.bg_layer.grid_columnconfigure(1, weight=1)
        self.bg_layer.grid_rowconfigure(0, weight=1)

        # 3. 사이드바 (메뉴)
        self.sidebar_frame = ctk.CTkFrame(self.bg_layer, width=200, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(6, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="🛡️ AI Guardian", font=self.font_title)
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 10))

        self.btn_dashboard = self.create_sidebar_button("대시보드", self.show_dashboard, 1)
        self.btn_scan = self.create_sidebar_button("개인정보 스캔", self.show_scan, 2)
        self.btn_wipe = self.create_sidebar_button("보안 삭제 (세탁)", self.show_wipe, 3)
        self.btn_clean = self.create_sidebar_button("디지털 청소", self.show_clean, 4)
        self.btn_startup = self.create_sidebar_button("시작프로그램 감시", self.show_startup, 5)
        self.btn_ai = self.create_sidebar_button("🤖 AI 보안 자문", self.show_ai, 6)

        # 4. 프레임 초기화
        # DashboardFrame에 '앱(self)' 자체를 넘겨서, 앱의 함수(show_scan 등)를 호출할 수 있게 함
        self.dashboard_frame = DashboardFrame(self.bg_layer, self.font_title, self.font_subtitle, self.font_body, app_instance=self)
        self.scan_frame = ScanFrame(self.bg_layer, self.font_title, self.font_body)
        self.wipe_frame = WipeFrame(self.bg_layer, self.font_title, self.font_body)
        self.clean_frame = CleanFrame(self.bg_layer, self.font_title, self.font_body, app_instance=self)
        self.startup_frame = StartupFrame(self.bg_layer, self.font_title, self.font_body)
        self.ai_frame = AIFrame(self.bg_layer, self.font_title, self.font_body)

        # Cleaner scan worker references (so we can stop/replace safely)
        self._cleaner_scanner = None
        self._cleaner_thread = None

        self.select_frame_by_name("dashboard")

        # 시작프로그램은 앱 시작 시 1회 검사(요청 반영: '디지털 청소' 자동 스캔은 제거)
        self.run_startup_check()

    def run_startup_check(self):
        monitor = StartupMonitor()
        status, new_items = monitor.check_for_changes()

        # 대시보드 + 상세 탭 동시 갱신
        self.dashboard_frame.update_startup_ui(status, len(new_items))
        self.startup_frame.update_ui(status, new_items)

    # App 클래스 내부
    def stop_cleaner_scan(self):
        """Stop any in-flight cleaner scan (best-effort)."""
        scanner = getattr(self, "_cleaner_scanner", None)
        if scanner is not None:
            try:
                scanner.stop()
            except Exception:
                pass
        self._cleaner_scanner = None
        self._cleaner_thread = None


    def run_cleaner_check(self, days=30, ignore_tiny=True, include_temp=True):
        """CleanerScanner를 백그라운드로 돌리고 CleanFrame에 큐를 연결"""
        # If a previous scan exists, stop it first
        self.stop_cleaner_scan()
        min_size = 1024 if ignore_tiny else 0
        q = queue.Queue()

        scanner = CleanerScanner(
            q,
            days=days,
            min_size_bytes=min_size,
            include_downloads=True,
            include_temp=include_temp,
        )

        self._cleaner_scanner = scanner

        t = threading.Thread(
            target=scanner.run_scan,
            kwargs=dict(
                days=days,
                ignore_tiny=ignore_tiny,
                include_downloads=True,
                include_temp=include_temp,
            ),
            daemon=True,
        )
        self._cleaner_thread = t
        t.start()

        # UI는 메인스레드에서 시작
        self.after(0, lambda: self.clean_frame.begin_scan(q, days=days, ignore_tiny=ignore_tiny, include_temp=include_temp))

    def create_sidebar_button(self, text, command, row):
        btn = ctk.CTkButton(
            self.sidebar_frame,
            text=text,
            command=command,
            font=self.font_bold,
            fg_color="transparent",
            text_color=("gray10", "#DCE4EE"),
            hover_color=("gray70", "gray30"),
            anchor="w",
            height=40,
        )
        btn.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        return btn

    def select_frame_by_name(self, name):
        for frame in [self.dashboard_frame, self.scan_frame, self.wipe_frame, self.clean_frame, self.startup_frame, self.ai_frame]:
            frame.grid_forget()

        if name == "dashboard":
            self.dashboard_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "scan":
            self.scan_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "wipe":
            self.wipe_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "clean":
            self.clean_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "startup":
            self.startup_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "ai":
            self.ai_frame.grid(row=0, column=1, sticky="nsew")

    def show_dashboard(self):
        self.select_frame_by_name("dashboard")

    def show_scan(self):
        self.select_frame_by_name("scan")

    def show_wipe(self):
        self.select_frame_by_name("wipe")

    def show_clean(self):
        self.select_frame_by_name("clean")
        self.clean_frame.ensure_scanned()

    def show_startup(self):
        self.select_frame_by_name("startup")

    def show_ai(self):
        self.select_frame_by_name("ai")
class DashboardFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_sub, f_body, app_instance):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        self.app = app_instance # 앱 본체를 저장해둠 (페이지 이동 함수 쓰려고)
        
        self.lbl_title = ctk.CTkLabel(self, text="안녕하세요! 현재 PC 보안 점수는 90점입니다.", font=f_title)
        self.lbl_title.pack(pady=30, padx=20, anchor="w")

        self.grid_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.grid_frame.pack(fill="both", expand=True, padx=20, pady=10)
        self.grid_frame.grid_columnconfigure((0, 1), weight=1)
        self.grid_frame.grid_rowconfigure((0, 1), weight=1)

        # 카드 생성 (command에 이동할 함수를 연결)
        self.card_scan, self.lbl_scan_title, self.lbl_scan_content = self.create_clickable_card(
            0, 0, "❓ 개인정보 스캔", "스캔이 필요합니다.", "#E67E22", f_sub, f_body, command=self.app.show_scan
        )
        self.create_clickable_card(0, 1, "🔒 보안 삭제 도구", "파일을 안전하게\n파쇄할 준비 완료", "#2980B9", f_sub, f_body, command=self.app.show_wipe)
        self.card_clean, self.lbl_clean_title, self.lbl_clean_content = self.create_clickable_card(
        1, 0, "🧹 디지털 청소", "검사 하기", "#D35400", f_sub, f_body, command=self.app.show_clean
        )
        self.card_startup, self.lbl_startup_title, self.lbl_startup_content = self.create_clickable_card(
            1, 1, "✅ 시작 프로그램", "검사 중...", "#27AE60", f_sub, f_body, command=self.app.show_startup
        )
        
    def create_clickable_card(self, row, col, title, content, color, f_sub, f_body, command):
        # 1. 카드 프레임 생성
        card = ctk.CTkFrame(self.grid_frame, corner_radius=15, border_width=2, border_color=color, cursor="hand2")
        card.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")
        
        # 2. 내부 텍스트 생성 (이벤트 전달을 위해 변수에 저장)
        lbl_t = ctk.CTkLabel(card, text=title, font=f_sub, text_color=color)
        lbl_t.pack(pady=(20, 10))
        
        lbl_c = ctk.CTkLabel(card, text=content, font=f_body)
        lbl_c.pack(pady=10)

        # 3. ✨ 마법의 호버 효과 함수 ✨
        def on_enter(event):
            # 마우스 올렸을 때: 배경색을 약간 밝게, 테두리 강조
            card.configure(fg_color=("gray85", "gray25")) 
        
        def on_leave(event):
            # 마우스 나갔을 때: 투명(또는 원래색)으로 복귀
            card.configure(fg_color=("gray95", "#2B2B2B")) # CustomTkinter 기본 카드색

        def on_click(event):
            # 클릭 시 명령어 실행
            command()

        # 4. 이벤트 바인딩 (카드, 제목, 내용 어디를 클릭/호버해도 작동하도록)
        for widget in [card, lbl_t, lbl_c]:
            widget.bind("<Enter>", on_enter)   # 마우스 들어옴
            widget.bind("<Leave>", on_leave)   # 마우스 나감
            widget.bind("<Button-1>", on_click) # 왼쪽 클릭

        return card, lbl_t, lbl_c
    
    # [핵심] 대시보드 상태를 업데이트하는 함수 추가
    def update_startup_ui(self, status, count):
        if status == "SAFE":
            self.card_startup.configure(border_color="#27AE60") # 초록
            self.lbl_startup_title.configure(text="✅ 시작 프로그램", text_color="#27AE60")
            self.lbl_startup_content.configure(text="안전함 (변동 없음)")
        elif status == "WARNING":
            self.card_startup.configure(border_color="#C0392B") # 빨강
            self.lbl_startup_title.configure(text="🚨 시작 프로그램", text_color="#C0392B")
            self.lbl_startup_content.configure(text=f"{count}개의 변경 감지됨!\n확인이 필요합니다.")
        elif status == "FIRST_RUN":
            self.card_startup.configure(border_color="#2980B9") # 파랑
            self.lbl_startup_title.configure(text="ℹ️ 감시 시작", text_color="#2980B9")
            self.lbl_startup_content.configure(text="기준 스냅샷 생성 완료")
    
    # [수정 2] 스캔 결과에 따라 대시보드 카드를 바꾸는 함수 추가
    def update_scan_ui(self, count):
        if count > 0:
            # 위험 요소 발견 시 (빨강)
            self.card_scan.configure(border_color="#C0392B")
            self.lbl_scan_title.configure(text=f"⚠️ 개인정보 노출", text_color="#C0392B")
            self.lbl_scan_content.configure(text=f"{count}건의 위험 정보가\n발견되었습니다.")
        else:
            # 안전할 때 (초록)
            self.card_scan.configure(border_color="#27AE60")
            self.lbl_scan_title.configure(text="✅ 개인정보 안전", text_color="#27AE60")
            self.lbl_scan_content.configure(text="발견된 개인정보가\n없습니다.")
        
    def update_clean_ui(self, summary: dict):
        count = summary.get("count", 0)
        total = summary.get("total_human", "0 B")
        d = summary.get("downloads_human", "0 B")
        t = summary.get("temp_human", "0 B")

        if count == 0:
            self.card_clean.configure(border_color="#27AE60")
            self.lbl_clean_title.configure(text="🧹 디지털 청소", text_color="#27AE60")
            self.lbl_clean_content.configure(text="정리할 파일 없음\n(Downloads/Temp)")
        else:
            self.card_clean.configure(border_color="#D35400")
            self.lbl_clean_title.configure(text="🧹 디지털 청소", text_color="#D35400")
            self.lbl_clean_content.configure(text=f"정리 가능: {total}\n(Downloads {d} / Temp {t})")
    
# --- 나머지 프레임들은 동일 ---

class ScanFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        self.scanner = SensitiveDataScanner()
        # [New] 보안 삭제 엔진 장착 (여기서 SecureWiper를 불러옵니다)
        self.wiper = SecureWiper() 

        self.is_scanning = False
        self.master_app = master 
        self.current_alert_count = 0 
        
        self.cached_results = [] 
        self.ignore_file = "scan_ignore_list.json"
        self.ignore_list = self.load_ignore_list()

        # UI 설정
        ctk.CTkLabel(self, text="🕵️ 개인정보 스캐너", font=f_title).pack(pady=20, padx=20, anchor="w")
        
        self.btn_start = ctk.CTkButton(self, text="스캔 시작", height=50, fg_color="#E67E22", 
                                     font=ctk.CTkFont(family="Malgun Gothic", size=16, weight="bold"), 
                                     command=self.start_thread)
        self.btn_start.pack(fill="x", padx=40, pady=(10, 5))

        self.var_show_ignored = ctk.BooleanVar(value=False)
        self.chk_show_ignored = ctk.CTkCheckBox(self, text="사용자 설정에 의해 숨겨진(무시된) 파일도 포함", 
                                                font=f_body, variable=self.var_show_ignored,
                                                command=self.refresh_view) 
        self.chk_show_ignored.pack(pady=5)

        self.lbl_status = ctk.CTkLabel(self, text="준비됨", font=f_body)
        self.lbl_status.pack(pady=5)
        
        # 프로그레스바
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)

        self.result_area = ctk.CTkScrollableFrame(self, label_text="스캔 결과", label_font=f_body)
        self.result_area.pack(fill="both", expand=True, padx=20, pady=20)

    # [수정됨] 보안 삭제 요청 처리 함수 (실제 삭제 로직 연결)
    def request_secure_delete(self, file_path, card_widget):
        # 1. 사용자 확인 (가장 중요)
        if not messagebox.askyesno("영구 삭제 확인", 
            f"정말 삭제하시겠습니까?\n\n파일: {os.path.basename(file_path)}\n\n⚠️ 주의: 보안 덮어쓰기가 수행되며, 절대 복구할 수 없습니다."):
            return

        # 2. UI 멈춤 방지를 위해 스레드로 실행
        threading.Thread(target=self._run_secure_delete, args=(file_path, card_widget), daemon=True).start()

    # [New] 실제 삭제를 수행하는 내부 함수 (스레드용)
    def _run_secure_delete(self, file_path, card_widget):
        # 보안 삭제 엔진 가동
        status, detail = self.wiper.wipe_file(file_path)
        
        # 결과 처리는 메인 UI 스레드에서 해야 안전함
        self.after(0, lambda: self._handle_delete_result(status, detail, card_widget))

    # [New] 삭제 결과에 따라 UI를 갱신하는 함수
    def _handle_delete_result(self, status, detail, card_widget):
        if status == "SUCCESS":
            messagebox.showinfo("삭제 완료", "파일이 안전하게 영구 삭제되었습니다.")
            
            # 1. 카드 제거
            card_widget.destroy()
            
            # 2. 카운트 감소 및 대시보드 갱신
            if self.current_alert_count > 0:
                self.current_alert_count -= 1
            
            self.lbl_status.configure(text=f"분석 완료! 총 {self.current_alert_count}개의 파일이 감지되었습니다.")
            
            try:
                self.master_app.dashboard_frame.update_scan_ui(self.current_alert_count)
            except: pass
            
            # 3. 다 지워서 목록이 비었을 때 메시지 표시
            if self.current_alert_count == 0:
                # 결과창이 비었으면 안내 메시지 추가
                for widget in self.result_area.winfo_children(): widget.destroy()
                ctk.CTkLabel(self.result_area, text="모든 항목이 처리되었습니다.").pack(pady=20)
                
        else:
            # 실패 사유별 친절한 에러 메시지
            msg_map = {
                "IN_USE": "파일이 현재 사용 중입니다.\n관련 프로그램을 종료하고 다시 시도해주세요.",
                "PERMISSION": "삭제 권한이 없습니다.\n관리자 권한으로 실행하거나 파일 권한을 확인하세요.",
                "SYSTEM_BLOCKED": "시스템 보호 파일은 안전을 위해 삭제가 차단됩니다.",
                "NOT_FOUND": "파일을 찾을 수 없습니다.\n이미 삭제되었거나 이동되었을 수 있습니다."
            }
            err_msg = msg_map.get(status, f"오류 발생: {detail}")
            messagebox.showerror("삭제 실패", err_msg)

    # --- 이하 기존 코드 유지 ---
    def reset_ui(self):
        self.is_scanning = False
        self.cached_results = []
        self.current_alert_count = 0
        
        self.btn_start.configure(state="normal", text="스캔 시작")
        self.lbl_status.configure(text="준비됨")
        
        self.progress.set(0)
        self.progress.pack_forget()
        
        self.var_show_ignored.set(False) 
        
        for widget in self.result_area.winfo_children():
            widget.destroy()

    def start_thread(self):
        if self.is_scanning: return
        self.is_scanning = True
        self.btn_start.configure(state="disabled", text="스캔 중...")
        
        self.result_area.pack_forget()
        self.progress.pack(fill="x", padx=40, pady=5)
        self.result_area.pack(fill="both", expand=True, padx=20, pady=20)
        
        for widget in self.result_area.winfo_children(): widget.destroy()
        threading.Thread(target=self.run_scan, daemon=True).start()

    def run_scan(self):
        try:
            def update_progress(val):
                self.progress.set(val / 100)
                self.lbl_status.configure(text=f"검사 중... {val}%")
            
            results = self.scanner.start_scan(update_progress)
            self.after(0, lambda: self.show_results(results))
        except Exception as e:
            print(f"스캔 오류: {e}")
            self.after(0, lambda: self.handle_scan_error(e))

    def handle_scan_error(self, error_msg):
        self.reset_ui() 
        messagebox.showerror("스캔 오류", f"스캔 도중 문제가 발생하여 중단되었습니다.\n\n[에러 내용]\n{error_msg}")

    def load_ignore_list(self):
        if not os.path.exists(self.ignore_file): return []
        try:
            with open(self.ignore_file, "r", encoding="utf-8") as f: return json.load(f)
        except: return []

    def save_ignore_list(self):
        try:
            with open(self.ignore_file, "w", encoding="utf-8") as f:
                json.dump(self.ignore_list, f, ensure_ascii=False, indent=4)
        except Exception as e: print(f"저장 실패: {e}")

    def refresh_view(self):
        if self.cached_results:
            self.show_results(self.cached_results)

    def dismiss_card_permanently(self, file_path, card_widget):
        if not messagebox.askyesno("검사 예외 처리", f"이 파일을 무시하시겠습니까?\n(체크박스를 켜야 다시 볼 수 있습니다)"):
            return
        if file_path not in self.ignore_list:
            self.ignore_list.append(file_path)
            self.save_ignore_list()
        self.refresh_view()

    def restore_card(self, file_path):
        if file_path in self.ignore_list:
            self.ignore_list.remove(file_path)
            self.save_ignore_list()
            messagebox.showinfo("복원 완료", "이제 이 파일은 다시 위험 항목으로 탐지됩니다.")
            self.refresh_view()

    def show_results(self, results):
        self.is_scanning = False
        self.cached_results = results 
        self.btn_start.configure(state="normal", text="다시 스캔하기")
        
        self.progress.pack_forget()

        filtered_results = []
        for item in results:
            if self.var_show_ignored.get():
                filtered_results.append(item) 
            else:
                if item['file_path'] not in self.ignore_list:
                    filtered_results.append(item) 
        
        self.current_alert_count = 0
        for item in filtered_results:
            if item['file_path'] not in self.ignore_list:
                self.current_alert_count += 1
        
        status_msg = f"분석 완료! {len(filtered_results)}개의 파일 표시 중"
        if self.var_show_ignored.get():
             status_msg += " (무시된 파일 포함)"
        self.lbl_status.configure(text=status_msg)
        
        try:
            self.master_app.dashboard_frame.update_scan_ui(self.current_alert_count)
        except: pass

        for widget in self.result_area.winfo_children(): widget.destroy()

        if not filtered_results:
            msg = "안전합니다! 발견된 정보가 없습니다."
            if len(results) > 0: msg += "\n(숨겨진 파일이 있습니다. 체크박스를 확인하세요)"
            ctk.CTkLabel(self.result_area, text=msg).pack(pady=20)
            return

        filtered_results.sort(key=lambda x: 0 if any(d['level'] == 'danger' for d in x['detections']) else 1)
        type_map = {'password': '비밀번호', 'pw': '비밀번호', 'jumin': '주민등록번호', 'phone': '전화번호', 'email': '이메일'}

        def create_card(item):
            detections = item['detections']
            file_path = item['file_path']
            is_ignored = file_path in self.ignore_list 

            is_danger = any(d['level'] == 'danger' for d in detections)
            risk_level = 'danger' if is_danger else 'warning'
            
            summary_text = f"총 {len(detections)}건의 개인정보 발견"
            if is_ignored: summary_text = "[무시됨] " + summary_text 

            full_detail_text = f"[전체 경로]\n{file_path}\n\n[상세 탐지 내역]\n"
            for d in detections:
                korean_type = type_map.get(d['type'], d['type'])
                full_detail_text += f"• [{d['line']}번째 줄] {korean_type}: {d['content'].strip()}\n"

            if is_ignored:
                icon, card_color, text_color, reason_color = "🚫 숨김", "#424949", "#BDC3C7", "#95A5A6"
            elif risk_level == 'danger':
                icon, card_color, text_color, reason_color = "🚨 위험", "#561818", "#FF9999", "#FFCCCC"
            else:
                icon, card_color, text_color, reason_color = "⚠️ 의심", "#564618", "#F5D0A9", "#FFF5E0"

            card = ctk.CTkFrame(self.result_area, fg_color=card_color)
            card.pack(fill="x", pady=3, padx=5)

            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=5, pady=5)

            ctk.CTkLabel(header, text=icon, width=60, font=("Malgun Gothic", 12, "bold"), 
                         text_color=text_color).pack(side="left", anchor="n")

            info_frame = ctk.CTkFrame(header, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True, padx=5)

            ctk.CTkLabel(info_frame, text=os.path.basename(file_path), font=("Malgun Gothic", 13, "bold"), 
                         anchor="w", text_color="white").pack(fill="x")
            
            ctk.CTkLabel(info_frame, text=f"🔎 {summary_text}", 
                                     font=("Malgun Gothic", 11), text_color=reason_color, anchor="w").pack(fill="x")

            detail_frame = ctk.CTkFrame(card, fg_color="#2B2B2B", corner_radius=5)
            ctk.CTkLabel(detail_frame, text=full_detail_text, 
                         font=("Malgun Gothic", 12), text_color="white", justify="left", anchor="w",
                         wraplength=400).pack(padx=10, pady=10, fill="x")

            def toggle_details():
                if detail_frame.winfo_viewable():
                    detail_frame.pack_forget()
                    btn_toggle.configure(text="▼")
                else:
                    detail_frame.pack(fill="x", padx=10, pady=(0, 10))
                    btn_toggle.configure(text="▲")

            btn_frame = ctk.CTkFrame(header, fg_color="transparent")
            btn_frame.pack(side="right")

            btn_toggle = ctk.CTkButton(btn_frame, text="▼", width=30, height=30, fg_color="transparent", 
                                       border_width=1, border_color=text_color, text_color=text_color,
                                       command=toggle_details)
            btn_toggle.pack(side="right", padx=2)

            # [수정됨] 삭제 버튼 클릭 시 새로 만든 request_secure_delete 호출
            ctk.CTkButton(btn_frame, text="삭제", width=50, height=30, fg_color="#C0392B", hover_color="#922B21",
                          command=lambda p=file_path, c=card: self.request_secure_delete(p, c)).pack(side="right", padx=2)
            
            if is_ignored:
                ctk.CTkButton(btn_frame, text="복원", width=50, height=30, fg_color="#27AE60", hover_color="#2ECC71",
                              command=lambda p=file_path: self.restore_card(p)).pack(side="right", padx=2)
            else:
                ctk.CTkButton(btn_frame, text="무시", width=50, height=30, fg_color="#7F8C8D", hover_color="#95A5A6",
                              command=lambda p=file_path, c=card: self.dismiss_card_permanently(p, c)).pack(side="right", padx=2)

            ctk.CTkButton(btn_frame, text="열기", width=50, height=30, fg_color="#3498DB",
                          command=lambda p=file_path: os.startfile(os.path.dirname(p))).pack(side="right", padx=2)

        for item in filtered_results:
            create_card(item)

class WipeFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")

        self.wiper = SecureWiper(chunk_size=1024 * 1024)  # 1MB
        self.is_wiping = False
        self.selected_paths: list[str] = []

        ctk.CTkLabel(self, text="🔒 완전 보안 삭제 (디지털 세탁소)", font=f_title).pack(pady=20, padx=20, anchor="w")

        # 안내 박스
        info = ctk.CTkFrame(self, fg_color="#2B2B2B", corner_radius=12)
        info.pack(fill="x", padx=20, pady=(0, 10))

        ctk.CTkLabel(
            info,
            text="• 3-pass 방식: 0으로 덮기 → 1로 덮기 → 난수로 덮기 → 삭제\n"
                 "• 파일이 사용 중이면 실패 알림\n"
                 "• 관리자 권한이 필요한 시스템 파일은 삭제 거부(안전장치)",
            font=f_body,
            justify="left",
            text_color="#DCE4EE"
        ).pack(padx=14, pady=12, anchor="w")

        # 드롭존(현재는 '선택 UI 중심' - 드래그&드롭은 옵션 패치 참고)
        self.drop_zone = ctk.CTkFrame(
            self,
            border_width=2,
            border_color="gray",
            corner_radius=20,
            fg_color=("#E0E0E0", "#2B2B2B"),
            height=220
        )
        self.drop_zone.pack(fill="x", padx=20, pady=10)
        self.drop_zone.pack_propagate(False)

        # 드롭존 내부 컨텐츠 프레임(가운데 정렬용)
        self.drop_content = ctk.CTkFrame(self.drop_zone, fg_color="transparent")
        self.drop_content.pack(fill="x", expand=True, padx=30, pady=10)


        self.lbl_drop = ctk.CTkLabel(
            self.drop_content,
            text="이곳에 파일을 드래그(옵션)하거나\n아래 버튼으로 파일을 선택하세요",
            font=ctk.CTkFont(family="Malgun Gothic", size=16, weight="bold"),
            justify="center",
            wraplength=520
        )
        self.lbl_drop.pack(pady=(16, 12), padx=10)

        self.sel_list = ctk.CTkScrollableFrame(self.drop_content, height=90, fg_color="transparent")
        self.sel_list.pack(fill="x", padx=10, pady=(0, 10))
        self.sel_list.pack_forget()  # 처음엔 숨김

        self.btn_select = ctk.CTkButton(
            self.drop_content,
            text="📁 파일 선택하기",
            font=f_body,
            height=42,
            command=self.pick_file
        )
        self.btn_select.pack(pady=(0, 20))


        # 선택된 파일 표시
        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(6, 0))

        ctk.CTkLabel(path_row, text="선택된 파일:", font=f_body).pack(side="left")
        self.entry_path = ctk.CTkEntry(path_row, placeholder_text="파일을 선택하세요", font=f_body)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(10, 10))
        self.entry_path.configure(state="disabled")

        self.btn_clear = ctk.CTkButton(path_row, text="지우기", width=90, fg_color="#555555", font=f_body, command=self.clear_file)
        self.btn_clear.pack(side="right")

        # 진행 상태
        self.lbl_status = ctk.CTkLabel(self, text="준비됨", font=f_body)
        self.lbl_status.pack(padx=20, pady=(10, 2), anchor="w")

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=20, pady=(0, 10))

        # 실행 버튼
        self.btn_run = ctk.CTkButton(
            self,
            text="🧺 영구 삭제 시작",
            height=48,
            font=ctk.CTkFont(family="Malgun Gothic", size=16, weight="bold"),
            fg_color="#2980B9",
            hover_color="#1F618D",
            command=self.confirm_and_start
        )
        self.btn_run.pack(fill="x", padx=20, pady=(8, 18))

                # --- DnD 바인딩 (옵션) ---
        ok1 = bind_drop_files(self.drop_zone, self.on_drop_files)
        ok2 = bind_drop_files(self.lbl_drop, self.on_drop_files)  # 라벨 위에 떨어뜨려도 동작
        if not (ok1 or ok2):
                # 루트가 TkinterDnD 기반이 아니면 DnD 메서드가 없어서 여기로 빠질 수 있음
                self.lbl_drop.configure(text="(드래그앤드롭 비활성)\n아래 버튼으로 파일을 선택하세요")
        # ⭐ 초기 드롭존 상태 세팅
        self.update_drop_zone_view()

    
    def update_drop_zone_view(self):
        paths = self.selected_paths or []

        # 1️⃣ 아무것도 선택 안 됐을 때 (초기 화면)
        if not paths:
            self.lbl_drop.configure(
                text="이곳에 파일을 드래그(옵션)하거나\n아래 버튼으로 파일을 선택하세요"
            )
            self.btn_select.configure(text="📁 파일 선택하기")

            # ⭐ 추가: 목록 UI 정리(잔상 제거)
            for w in self.sel_list.winfo_children():
                w.destroy()
            self.sel_list.pack_forget()

            return

        # ---- 아래는 그대로 ----
        lines = []
        for p in paths[:5]:
            icon = "📁" if Path(p).is_dir() else "📄"
            lines.append(f"{icon} {p}")

        if len(paths) > 5:
            lines.append(f"... 외 {len(paths) - 5}개")

        # 선택된 게 있을 때
        self.lbl_drop.configure(text=f"총 {len(paths)}개 선택됨", wraplength=520)
        self.btn_select.configure(text="추가 선택")

        # --- 선택 목록 렌더링 ---
        for w in self.sel_list.winfo_children():
            w.destroy()

        self.sel_list.pack(fill="x", padx=10, pady=(0, 10))

        for p in paths:
            row = ctk.CTkFrame(self.sel_list, fg_color="transparent")
            row.pack(fill="x", pady=2)

            icon = "📁" if Path(p).is_dir() else "📄"

            lbl = ctk.CTkLabel(row, text=f"{icon} {p}", anchor="w", justify="left")
            lbl.pack(side="left", fill="x", expand=True, padx=(5, 0))

            ctk.CTkButton(
                row, text="❌", width=36,
                command=lambda pp=p: self.remove_selected_path(pp)
            ).pack(side="right")


    
    def remove_selected_path(self, path: str):
        # 1) 데이터에서 제거
        self.selected_paths = [p for p in (self.selected_paths or []) if p != path]

        # 2) 엔트리/라벨 갱신
        self._sync_entry_path()

        # 3) 드롭존/목록 다시 그리기 (⭐ 핵심)
        self.update_drop_zone_view()



    
    def on_drop_files(self, files: list[str]):
        if not files:
            return

        valid = []
        for x in files:
            p = Path(x)
            if p.exists():
                valid.append(str(p))

        if not valid:
            self.lbl_status.configure(text="드롭된 경로를 찾을 수 없어요.")
            return

        self.add_selected_paths(valid)



    def set_selected_paths(self, paths: list[str]):
        self.selected_paths = paths

        self.entry_path.configure(state="normal")
        self.entry_path.delete(0, "end")

        if len(paths) == 1:
            self.entry_path.insert(0, paths[0])
            self.lbl_status.configure(text="선택됨")
        else:
            self.entry_path.insert(0, f"{len(paths)}개 선택됨")
            self.lbl_status.configure(text=f"{len(paths)}개 선택됨")

        self.entry_path.configure(state="disabled")
        self.progress.set(0)
        self.update_drop_zone_view()

    def add_selected_paths(self, paths: list[str]):
        paths = self._normalize_paths(paths)
        if not paths:
            return

        self.selected_paths = self._merge_unique(self.selected_paths or [], paths)
        self.update_drop_zone_view()
        self._sync_entry_path()

    def _sync_entry_path(self):
        paths = self.selected_paths or []
        self.entry_path.configure(state="normal")
        self.entry_path.delete(0, "end")
        if len(paths) == 0:
            self.entry_path.insert(0, "")
        elif len(paths) == 1:
            self.entry_path.insert(0, paths[0])
        else:
            self.entry_path.insert(0, f"{len(paths)}개 선택됨")
        self.entry_path.configure(state="disabled")



    def _normalize_paths(self, paths: list[str]) -> list[str]:
        out = []
        for p in paths:
            if not p:
                continue
            s = str(p).strip().replace("\\", "/")
            if s:
                out.append(s)
        return out

    def _merge_unique(self, base: list[str], add: list[str]) -> list[str]:
        seen = set()
        merged = []
        for x in base + add:
            if x in seen:
                continue
            seen.add(x)
            merged.append(x)
        return merged


    # ---------- UI Helpers ----------
    def set_path(self, path: str):
        self.selected_path = path
        self.entry_path.configure(state="normal")
        self.entry_path.delete(0, "end")
        self.entry_path.insert(0, path)
        self.entry_path.configure(state="disabled")

    def clear_file(self):
        if self.is_wiping:
            messagebox.showinfo("알림", "삭제 진행 중에는 변경할 수 없습니다.")
            return
        self.selected_paths = []
        self.progress.set(0)
        self.lbl_status.configure(text="준비됨")
        self.update_drop_zone_view()
        self._sync_entry_path()


    def pick_file(self):
        if self.is_wiping:
            return

        new_paths = filedialog.askopenfilenames()
        if new_paths:
            self.add_selected_paths(list(new_paths))



    # ---------- Workflow ----------
    def confirm_and_start(self):
        if self.is_wiping:
            return

        paths = [p for p in (self.selected_paths or []) if p and str(p).strip()]
        if not paths:
            messagebox.showwarning("안내", "먼저 삭제할 파일/폴더를 선택하세요.")
            return

        # 존재 검사
        missing = [p for p in paths if not os.path.exists(p)]
        if missing:
            messagebox.showwarning("안내", f"존재하지 않는 경로가 포함되어 있습니다.\n\n{missing[0]}")
            return

        msg = build_wipe_confirm_message(paths)

        ok = messagebox.askyesno(
            "정말 영구 삭제할까요?",
            msg
        )

        if not ok:
            return

        self.is_wiping = True
        self.btn_run.configure(state="disabled")
        self.btn_select.configure(state="disabled")
        self.btn_clear.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="삭제 준비 중...")

        threading.Thread(target=self._wipe_thread, args=(paths,), daemon=True).start()


    def _wipe_thread(self, paths: list[str]):
        stage_map = {
            "PASS1_ZERO": "PASS 1/3: 0으로 덮는 중",
            "PASS2_ONE": "PASS 2/3: 1로 덮는 중",
            "PASS3_RANDOM": "PASS 3/3: 난수로 덮는 중",
        }

        total_items = len(paths)

        for idx, path in enumerate(paths, start=1):
            media = get_media_type_for_path(path)
            passes = 1 if media == "SSD" else 3  # SSD=1-pass, HDD(or UNKNOWN)=3-pass

            # ✅ path마다 wiper를 passes에 맞게 새로 만들어서 적용 (가장 깔끔)
            wiper = SecureWiper(chunk_size=1024 * 1024, passes=passes)

            def progress_cb(written, total, stage, _idx=idx):
                pct = 0 if total == 0 else (written / total)
                text = stage_map.get(stage, stage)
                self.after(0, lambda p=pct, t=text, i=_idx:
                        self._update_progress(p, f"[{i}/{total_items}] ({media}/{passes}-pass) {t}"))

            status, detail = wiper.wipe_path(path, progress_cb=progress_cb)

            if status != "SUCCESS":
                self.after(0, lambda s=status, d=detail: self._finish(s, d))
                return

        self.after(0, lambda: self._finish("SUCCESS", "모두 삭제 완료"))


    def _update_progress(self, pct: float, text: str):
        self.progress.set(max(0.0, min(1.0, pct)))
        self.lbl_status.configure(text=f"{text}... {int(pct*100)}%")

    def _finish(self, status: str, detail: str):
        self.is_wiping = False
        self.btn_run.configure(state="normal")
        self.btn_select.configure(state="normal")
        self.btn_clear.configure(state="normal")

        if status == "SUCCESS":
            self.progress.set(1.0)               # ✅ 완료 상태 유지
            self.lbl_status.configure(text="✅ 삭제 완료")
            self.update_idletasks()               # ✅ UI 즉시 반영

            messagebox.showinfo("완료", "보안 삭제가 완료되었습니다.")
            self.clear_file()                     # ✅ 여기서 progress 0으로 리셋
            return
        
        # ❌ 실패한 경우
        self.lbl_status.configure(text=f"❌ 삭제 실패: {status}")
        self.update_idletasks()

        # 실패 사유별 메시지
        if status == "IN_USE":
            messagebox.showerror("실패", "다른 프로그램에서 사용 중인 파일이라 삭제에 실패했습니다.")
        elif status == "PERMISSION":
            messagebox.showerror("거부", "권한 부족(관리자 권한/보호 파일)으로 삭제가 거부되었습니다.")
        elif status == "SYSTEM_BLOCKED":
            messagebox.showwarning("거부", "시스템 보호 파일/경로는 삭제가 거부됩니다.")
        elif status == "NOT_FOUND":
            messagebox.showerror("실패", "파일을 찾을 수 없습니다.")
        else:
            messagebox.showerror("실패", f"삭제 실패: {detail}")

        self.progress.set(0.0)   # ✅ 실패했을 때만 리셋

        # 디버깅용 detail은 필요할 때만 띄워도 됨
        # print("wipe detail:", detail)
        self.lbl_status.configure(text=f"❌ 실패: {status}")


class CleanFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body, app_instance=None, **kwargs):
        super().__init__(master, corner_radius=0, fg_color="transparent", **kwargs)
        self.app = app_instance
        self.f_body = f_body

       # [1] 에러 방지: 변수 선언을 UI 배치보다 반드시 먼저 해야 합니다!
        self.var_days = ctk.StringVar(value="30")
        self.var_ignore_tiny = ctk.BooleanVar(value=True)
        self.var_include_temp = ctk.BooleanVar(value=True)
        self.show_safe_only = False

        # [2] 상태 및 제어 변수 초기화
        self._all_files: list[DormantFile] = []
        self._selected: dict[str, bool] = {}
        self._seen_paths: set[str] = set()
        self._page = 1
        self._page_size = 30

        self._scan_queue: queue.Queue | None = None
        self._scan_running = False
        self._scan_started = 0.0
        self._poll_job = None
        self._render_job = None
        self._scanned_once = False

        # [3] 레이아웃 설정
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)

        title_lbl = ctk.CTkLabel(self, text="🧹 디지털 찌꺼기 청소", font=f_title)
        title_lbl.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")

        # ===== 옵션 바 (개선된 UI) =====
        opt = ctk.CTkFrame(self, fg_color="transparent")
        opt.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 15))
        
        # 중간 여백 자동 조절 (4번 열이 늘어나면서 스캔 버튼을 오른쪽 끝으로 밀어냄)
        opt.grid_columnconfigure(4, weight=1) 

        # 1. 기준(일) - opt에 직접 배치
        ctk.CTkLabel(opt, text="기준(일):", font=f_body).grid(row=0, column=0, padx=(0, 5))
        self.entry_days = ctk.CTkEntry(opt, width=50, height=32, textvariable=self.var_days, font=f_body)
        self.entry_days.grid(row=0, column=1, padx=(0, 15))

        # 2. 체크박스들 - opt에 직접 배치
        self.chk_ignore = ctk.CTkCheckBox(opt, text="1KB 미만 무시", variable=self.var_ignore_tiny, 
                                          font=f_body, checkbox_width=18, checkbox_height=18)
        self.chk_ignore.grid(row=0, column=2, padx=(0, 12))

        self.chk_temp = ctk.CTkCheckBox(opt, text="TEMP 포함", variable=self.var_include_temp, 
                                        font=f_body, checkbox_width=18, checkbox_height=18)
        self.chk_temp.grid(row=0, column=3, padx=(0, 15))

        # 3. 안전 필터 버튼 (텍스트 깨짐 방지 위해 width 넉넉히 설정)
        self.filter_btn = ctk.CTkButton(
            opt, text="안전필터: OFF", command=self.toggle_filter,
            fg_color="#34495E", hover_color="#2C3E50",
            width=150, height=32, font=f_body
        )
        self.filter_btn.grid(row=0, column=4, sticky="w") # 왼쪽 정렬

        # 4. 오른쪽 스캔하기 버튼 (강조)
        self.btn_refresh = ctk.CTkButton(
            opt, text="스캔하기", 
            font=ctk.CTkFont(family="Malgun Gothic", size=14, weight="bold"),
            fg_color="#3498DB", hover_color="#2980B9",
            command=self.refresh_scan, 
            width=110, height=32
        )
        self.btn_refresh.grid(row=0, column=5, sticky="e")

        # ===== 진행상황 UI =====
        self.scan_ui = ctk.CTkFrame(self, corner_radius=10)
        self.scan_stage = ctk.CTkLabel(self.scan_ui, text="대기 중", font=f_body)
        self.scan_stage.pack(anchor="w", padx=12, pady=(10, 2))

        self.scan_stats = ctk.CTkLabel(self.scan_ui, text="스캔: 0 | 발견: 0 | 0 B | 0 files/s",
                                       font=f_body, text_color="#95A5A6")
        self.scan_stats.pack(anchor="w", padx=12, pady=(0, 8))

        self.scan_bar = ctk.CTkProgressBar(self.scan_ui, mode="indeterminate")
        self.scan_bar.pack(fill="x", padx=12, pady=(0, 8))

        self.scan_log = ctk.CTkTextbox(self.scan_ui, height=90, font=f_body)
        self.scan_log.configure(state="disabled")
        self.scan_log.pack(fill="x", padx=12, pady=(0, 12))

        self.scan_ui.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 10))
        self.scan_ui.grid_remove()

        # 요약 라벨
        self.lbl_summary = ctk.CTkLabel(self, text="스캔 대기 중", font=f_body, text_color="#F39C12")
        self.lbl_summary.grid(row=3, column=0, sticky="w", padx=20, pady=(0, 10))

        # 목록(페이지네이션: 현재 페이지만 렌더)
        self.list_frame = ctk.CTkScrollableFrame(self, label_text="정리 대상 파일", label_font=f_body, height=330)
        self.list_frame.grid(row=4, column=0, sticky="nsew", padx=20, pady=(0, 10))

        # 페이지 네비게이션
        nav = ctk.CTkFrame(self, fg_color="transparent")
        nav.grid(row=5, column=0, sticky="ew", padx=20, pady=(0, 10))

        self.btn_prev = ctk.CTkButton(nav, text="◀ 이전", width=120, command=self.prev_page)
        self.btn_prev.pack(side="left")

        self.lbl_page = ctk.CTkLabel(nav, text="Page 1/1", font=f_body)
        self.lbl_page.pack(side="left", padx=12)

        self.btn_next = ctk.CTkButton(nav, text="다음 ▶", width=120, command=self.next_page)
        self.btn_next.pack(side="left")

        # 하단 버튼
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=6, column=0, sticky="ew", padx=20, pady=(0, 20))

        self.btn_select_all = ctk.CTkButton(bottom, text="전체 선택", font=f_body, width=120, command=self.select_all)
        self.btn_select_all.pack(side="left")

        self.btn_clear = ctk.CTkButton(bottom, text="선택 해제", font=f_body, width=120, fg_color="#777777",command=self.clear_selection)
        self.btn_clear.pack(side="left", padx=10)

        self.btn_clean = ctk.CTkButton(bottom, text="선택 삭제", height=45, font=f_body, fg_color="#27AE60",command=self.clean_selected)
        self.btn_clean.pack(side="right")

        self.btn_clean_all = ctk.CTkButton(bottom, text="전체 삭제", height=45, font=f_body, fg_color="#C0392B",command=self.clean_all)
        self.btn_clean_all.pack(side="right", padx=10)

        self._render_empty("스캔 결과가 여기에 표시됩니다.")

    # ---------- UI helpers ----------
    def _log(self, msg: str):
        self.scan_log.configure(state="normal")
        self.scan_log.insert("end", msg + "\n")
        self.scan_log.see("end")
        self.scan_log.configure(state="disabled")

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        for w in [self.btn_refresh, self.entry_days, self.chk_ignore, self.chk_temp, self.filter_btn,
                  self.btn_select_all, self.btn_clear, self.btn_clean, self.btn_clean_all,
                  self.btn_prev, self.btn_next]:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _render_empty(self, msg: str):
        for w in self.list_frame.winfo_children():
            w.destroy()
        ctk.CTkLabel(self.list_frame, text=msg, font=self.f_body).pack(pady=20)

    # ---------- public ----------
    def ensure_scanned(self):
        if not self._scanned_once:
            self._scanned_once = True
            self.refresh_scan()

    def toggle_filter(self):
        self.show_safe_only = not self.show_safe_only
        # 짧은 문구 사용으로 버튼 깨짐 방지
        status = "ON" if self.show_safe_only else "OFF"
        self.filter_btn.configure(text=f"안전필터: {status}")
        
        # 상태에 따른 색상 변경
        self.filter_btn.configure(fg_color="#27AE60" if self.show_safe_only else "#34495E")
        
        self._page = 1
        self._render_page()
    # ---------- scan ----------
    def _parse_days(self) -> int:
        try:
            d = int(self.var_days.get().strip())
            return max(1, min(d, 3650))
        except Exception:
            return 30

    def refresh_scan(self):
        if self._scan_running:
            return
        if self.app is None:
            messagebox.showerror("오류", "App 인스턴스를 찾을 수 없습니다. (clean_frame 생성부 확인)")
            return
        days = self._parse_days()
        ignore_tiny = bool(self.var_ignore_tiny.get())
        include_temp = bool(self.var_include_temp.get())

        # 스캔 시작
        self.lbl_summary.configure(text="스캔 준비 중...")
        self.app.run_cleaner_check(days=days, ignore_tiny=ignore_tiny, include_temp=include_temp)

    def begin_scan(self, q, days=30, ignore_tiny=True, include_temp=True):
        """App에서 스캔 스레드를 시작한 직후, UI가 큐 폴링을 시작하도록 호출."""
        # 초기화
        self._scan_queue = q
        self._scan_running = True
        self._scan_started = time.time()
        self._all_files.clear()
        self._selected.clear()
        self._seen_paths.clear()
        self._page = 1

        # UI
        self.lbl_summary.configure(text="스캔 진행 중...")
        self.scan_stage.configure(text="스캔 시작")
        self.scan_stats.configure(text="스캔: 0 | 발견: 0 | 0 B | 0 files/s")
        self.scan_ui.grid()
        self.scan_bar.start()

        # 로그
        self.scan_log.configure(state="normal")
        self.scan_log.delete("1.0", "end")
        self.scan_log.configure(state="disabled")
        self._log(f"옵션: days={days}, ignore_tiny={ignore_tiny}, include_temp={include_temp}")

        self._set_controls_enabled(False)
        self._poll_queue()

    def _poll_queue(self):
        # ✅ 큐가 None이거나 스캔이 끝난 상태면 안전하게 종료
        if not self._scan_running or self._scan_queue is None:
            return

        q = self._scan_queue
        if q is None:
            self._scan_running = False
            self._poll_job = None
            return

        # UI 렉 방지: 한 번에 너무 많이 처리하지 않음
        for _ in range(60):
            try:
                ev = q.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break
            self._handle_event(ev)

        if self._scan_running and self._scan_queue is not None:
            self._poll_job = self.after(30, self._poll_queue)
        else:
            self._poll_job = None

    def _handle_event(self, ev: dict):
        t = ev.get("type")

        if t == "stage":
            msg = ev.get("message") or ev.get("text") or ""
            if msg:
                self.scan_stage.configure(text=msg)
                self._log(msg)

        elif t == "stats":
            scanned = int(ev.get("scanned", 0))
            found = int(ev.get("found", 0))
            total_bytes = int(ev.get("total_bytes", ev.get("size", 0)))
            elapsed = float(ev.get("elapsed", max(time.time() - self._scan_started, 0.001)))

            speed = scanned / max(elapsed, 0.001)
            self.scan_stats.configure(
                text=f"스캔: {scanned:,} | 발견: {found:,} | {human_size(total_bytes)} | {speed:,.1f} files/s"
            )

        elif t == "batch":
            files = ev.get("files", []) or []
            if files:
                # 중복 제거는 set으로 누적 관리 (O(1))
                for df in files:
                    path_str = str(df.path)
                    if path_str in self._seen_paths:
                        continue
                    self._seen_paths.add(path_str)

                    self._all_files.append(df)

                    # 기본적으로 새로 발견된 파일은 선택 상태로 둠
                    if path_str not in self._selected:
                        self._selected[path_str] = True

                self._schedule_render()

        elif t == "done":
            # 1. 데이터 정리
            files = ev.get("files")
            if files is not None:
                uniq = []
                seen = set()
                for df in files:
                    k = str(df.path)
                    if k not in seen:
                        seen.add(k)
                        uniq.append(df)
                self._all_files = uniq

                for df in self._all_files:
                    k = str(df.path)
                    if k not in self._selected:
                        self._selected[k] = True

            # 2. 요약 표시
            summary = ev.get("summary") or summarize(self._all_files)
            count = summary.get("count", len(self._all_files))
            total = summary.get("total_human", human_size(sum(f.size_bytes for f in self._all_files)))
            self.lbl_summary.configure(text=f"정리 가능한 파일: {count}개 / {total}")

            # 3. UI 상태 복구
            self.scan_stage.configure(text="완료 ✅")
            self.scan_bar.stop()
            self.scan_ui.grid_remove()

            self._scan_running = False
            self._scan_queue = None

            # 🌟 [중요] 버튼들 다시 활성화 🌟
            self._set_controls_enabled(True)

            self._page = 1
            self._render_page()

        elif t == "error":
            msg = ev.get("message") or ev.get("text") or "오류"
            self.scan_stage.configure(text="오류 발생 ❌")
            self.scan_bar.stop()
            self._log(f"[ERROR] {msg}")
            self._scan_running = False
            self._scan_queue = None
            messagebox.showerror("스캔 오류", msg)

    def _is_safe(self, df: DormantFile) -> bool:
        try:
            # Cleaner.py의 함수가 정상적으로 import 되었는지 확인 필수
            level, _ = classify_delete_safety(df)
            return level == "SAFE"
        except NameError:
            # 함수가 없으면 보수적으로 모두 '확인 필요'로 표시
            return False
        except Exception:
            return False

    def _filtered_files(self) -> list[DormantFile]:
        if not self.show_safe_only:
            return list(self._all_files)
        return [df for df in self._all_files if self._is_safe(df)]

    def prev_page(self):
        if self._page > 1:
            self._page -= 1
            self._render_page()

    def next_page(self):
        total_pages = max(1, math.ceil(len(self._filtered_files()) / self._page_size))
        if self._page < total_pages:
            self._page += 1
            self._render_page()

    def _render_page(self):
        self._render_job = None

        # 1. 필터링된 데이터 준비
        files = self._filtered_files()
        total = len(files)
        total_pages = max(1, math.ceil(total / self._page_size))
        self._page = max(1, min(self._page, total_pages))

        # 2. 페이지 라벨 업데이트 
        self.lbl_page.configure(text=f"Page {self._page}/{total_pages}")

        # [핵심 최적화] 3. 스캔 중이고, 이미 1페이지 분량의 데이터가 화면에 있다면 
        # 굳이 전체를 다시 그리지 않고 통계 수치만 업데이트하도록 리턴합니다.
        current_widgets = self.list_frame.winfo_children()
        if self._scan_running and len(current_widgets) >= self._page_size:
            # 1페이지가 꽉 찼다면, 스캔이 끝날 때까지 리스트 갱신을 멈춰서 렉을 방지합니다.
            return

        # 4. 화면 청소
        for w in current_widgets:
            w.destroy()

        # 5. 빈 화면 처리
        if total == 0:
            if self._scan_running:
                self._render_empty("스캔 중... (파일이 발견되면 여기에 표시됩니다)")
            else:
                self._render_empty("표시할 파일이 없습니다.")
            return

        # 6. 실제 항목 생성 (현재 페이지만)
        start = (self._page - 1) * self._page_size
        end = start + self._page_size
        for df in files[start:end]:
            self._create_file_row(df)
            
        # 7. UI 즉시 반영 강제 (렉 완화 도움)
        self.update_idletasks()
    
    def _schedule_render(self):
        """매번 화면을 그리지 않고 0.1초 뒤에 한 번만 그리도록 예약 (성능 최적화)"""
        if self._render_job:
            self.after_cancel(self._render_job)
        self._render_job = self.after(100, self._render_page)

    def _create_file_row(self, df: DormantFile):
        # 한 줄 UI: [체크박스] [파일 정보(2줄)] [오른쪽 상태 배지]
        row = ctk.CTkFrame(self.list_frame, corner_radius=10)
        row.pack(fill="x", padx=8, pady=6)

        # 3열: 체크 / 텍스트(가변) / 배지(고정)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, minsize=130)

        path_key = str(df.path)
        v = ctk.BooleanVar(value=self._selected.get(path_key, True))

        def _on_toggle(*_):
            self._selected[path_key] = bool(v.get())

        v.trace_add("write", _on_toggle)

        chk = ctk.CTkCheckBox(row, text="", variable=v, width=32)
        chk.grid(row=0, column=0, padx=(10, 8), pady=10, sticky="w")

        # 오른쪽 배지(고정 폭)
        is_safe = self._is_safe(df)
        tag_text = "✅ 안전" if is_safe else "⚠ 확인"
        tag_color = "#2ECC71" if is_safe else "#F1C40F"

        # 텍스트가 오른쪽을 침범하지 않도록 wraplength를 동적으로 계산
        w = self.list_frame.winfo_width()
        if w < 200:
            w = 760  # 초기 렌더 시 대비(고정 창 기준)
        wrap = max(260, w - 32 - 10 - 130 - 60)

        info = f"[{df.root}] {df.path.name}  •  {human_size(df.size_bytes)}  •  {df.last_modified:%Y-%m-%d}\n{df.path}"
        lbl = ctk.CTkLabel(row, text=info, font=self.f_body, anchor="w", justify="left", wraplength=wrap)
        lbl.grid(row=0, column=1, padx=(0, 8), pady=10, sticky="w")

        tag_frame = ctk.CTkFrame(row, fg_color="transparent", width=130)
        tag_frame.grid(row=0, column=2, padx=(0, 10), pady=10, sticky="e")
        tag_frame.grid_propagate(False)

        tag_lbl = ctk.CTkLabel(tag_frame, text=tag_text, text_color=tag_color, width=120, anchor="center", font=self.f_body)
        tag_lbl.pack(fill="both", expand=True)
    def select_all(self):
        for df in self._filtered_files():
            self._selected[str(df.path)] = True
        self._render_page()

    def clear_selection(self):
        for df in self._filtered_files():
            self._selected[str(df.path)] = False
        self._render_page()

    def _selected_files(self) -> list[DormantFile]:
        selected_paths = {p for p, ok in self._selected.items() if ok}
        return [df for df in self._all_files if str(df.path) in selected_paths]

    def clean_selected(self):
        selected = self._selected_files()
        if not selected:
            messagebox.showinfo("안내", "삭제할 파일이 선택되지 않았습니다.")
            return

        total = sum(f.size_bytes for f in selected)
        ok = messagebox.askyesno(
            "삭제 확인",
            f"선택한 {len(selected)}개 파일을 '일반 삭제'합니다.\n총 크기: {human_size(total)}\n\n계속할까요?"
        )
        if not ok:
            return

        deleted, failed = delete_files(selected)

        msg = f"삭제 완료: {len(deleted)}개"
        if failed:
            msg += f"\n실패: {len(failed)}개 (권한/사용중 등)"
        messagebox.showinfo("결과", msg)

        self.refresh_scan()

    def clean_all(self):
        files = self._filtered_files()
        if not files:
            messagebox.showinfo("안내", "삭제할 파일이 없습니다.")
            return

        total = sum(f.size_bytes for f in files)
        ok = messagebox.askyesno(
            "전체 삭제 확인",
            f"현재 표시 중인 파일 {len(files)}개를 '일반 삭제'합니다.\n총 크기: {human_size(total)}\n\n계속할까요?"
        )
        if not ok:
            return

        deleted, failed = delete_files(files)

        msg = f"삭제 완료: {len(deleted)}개"
        if failed:
            msg += f"\n실패: {len(failed)}개 (권한/사용중 등)"
        messagebox.showinfo("결과", msg)

        self.refresh_scan()

class StartupFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        
        self.monitor = StartupMonitor()
        self.f_body = f_body # 폰트 저장해둠
        
        ctk.CTkLabel(self, text="🚀 시작 프로그램 감시", font=f_title).pack(pady=20, padx=20, anchor="w")
        
        # 1. 상태 박스
        self.status_box = ctk.CTkFrame(self, fg_color="gray", corner_radius=10, height=80)
        self.status_box.pack(fill="x", padx=20, pady=10)
        
        self.lbl_status = ctk.CTkLabel(self.status_box, text="검사 중...", font=ctk.CTkFont(family="Malgun Gothic", size=18, weight="bold"), text_color="white")
        self.lbl_status.place(relx=0.5, rely=0.5, anchor="center")
        
        # 2. 감지된 항목 리스트 (여기에 버튼이 들어감)
        self.lbl_warning_detail = ctk.CTkLabel(self, text="[새로 발견된 프로그램 - 승인 필요]", text_color="#E74C3C", font=f_body)
        # 스크롤 가능한 프레임으로 변경 (버튼을 넣기 위해)
        self.scroll_list = ctk.CTkScrollableFrame(self, height=200, label_text="감지 목록")
        
        # 3. 수동 검사 버튼
        self.btn_refresh = ctk.CTkButton(self, text="🔄 다시 검사하기", command=self.run_manual_check, font=f_body, fg_color="#555555")
        self.btn_refresh.pack(side="bottom", pady=20)

    def run_manual_check(self):
        # 수동 버튼 눌렀을 때 실행
        status, new_items = self.monitor.check_for_changes()
        self.update_ui(status, new_items)

    def update_ui(self, status, new_items):
        # UI 초기화 (기존 목록 지우기)
        self.lbl_warning_detail.pack_forget()
        self.scroll_list.pack_forget()
        for widget in self.scroll_list.winfo_children():
            widget.destroy()

        if status == "SAFE":
            self.status_box.configure(fg_color="#1E8449") # 초록
            self.lbl_status.configure(text="✅ 현재 시스템은 안전합니다.")
            
        elif status == "FIRST_RUN":
            self.status_box.configure(fg_color="#2980B9") # 파랑
            self.lbl_status.configure(text="ℹ️ 기준 스냅샷을 생성했습니다.")
            
        elif status == "WARNING":
            self.status_box.configure(fg_color="#C0392B") # 빨강
            self.lbl_status.configure(text=f"🚨 {len(new_items)}개의 새로운 시작프로그램 감지!")
            
            # 리스트 보여주기
            self.lbl_warning_detail.pack(pady=(10, 5))
            self.scroll_list.pack(fill="x", padx=20)
            
            # [핵심] 각 아이템마다 '승인' 버튼 생성
            for item in new_items:
                self.create_item_row(item)

    def create_item_row(self, item):
        row = ctk.CTkFrame(self.scroll_list)
        row.pack(fill="x", pady=5)
        
        # 프로그램 정보 (이름, 경로)
        info_text = f"{item['name']}\n({item['path']})"
        ctk.CTkLabel(row, text=info_text, anchor="w", font=self.f_body).pack(side="left", padx=10, pady=5)
        
        # 승인 버튼
        btn_approve = ctk.CTkButton(
            row, 
            text="승인 (안전함)", 
            width=100, 
            fg_color="#27AE60", 
            hover_color="#2ECC71",
            command=lambda: self.approve_item(item)
        )
        btn_approve.pack(side="right", padx=10)

    def approve_item(self, item):
        # 1. 로직에게 "이거 저장해!"라고 명령
        success = self.monitor.approve_new_program(item['name'], item['path'])
        
        if success:
            # 2. 성공했으면 화면 갱신 (다시 검사하면 이제 SAFE로 뜰 것임)
            print(f"승인 완료: {item['name']}")
            self.run_manual_check() # UI 업데이트
        else:
            print("승인 실패")

class AIFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        ctk.CTkLabel(self, text="🤖 AI 보안 자문", font=f_title).pack(pady=20, padx=20, anchor="w")
        self.chat_history = ctk.CTkTextbox(self, state="disabled", font=f_body)
        self.chat_history.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        self.input_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.input_frame.pack(fill="x", padx=20, pady=20)
        self.entry_msg = ctk.CTkEntry(self.input_frame, placeholder_text="내용을 입력하세요...", font=f_body, height=40)
        self.entry_msg.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.btn_send = ctk.CTkButton(self.input_frame, text="전송", font=f_body, width=100, height=40, fg_color="#8E44AD")
        self.btn_send.pack(side="right")

if __name__ == "__main__":
    app = App()
    app.mainloop()