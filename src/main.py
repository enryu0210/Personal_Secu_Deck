import customtkinter as ctk
import os
import threading
import json
import re
from pathlib import Path
from tkinterdnd2 import TkinterDnD
from tkinter import messagebox
from tkinter import filedialog
from startup_checker import StartupMonitor
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
        self.clean_frame = CleanFrame(self.bg_layer, self.font_title, self.font_body)
        self.startup_frame = StartupFrame(self.bg_layer, self.font_title, self.font_body)
        self.ai_frame = AIFrame(self.bg_layer, self.font_title, self.font_body)

        self.select_frame_by_name("dashboard")

        self.run_startup_check()

    def run_startup_check(self):
        # 1. 감시자(Monitor) 소환해서 검사 실행
        monitor = StartupMonitor()
        status, new_items = monitor.check_for_changes()
        
        # 2. 대시보드 업데이트 (방금 만든 함수 호출)
        self.dashboard_frame.update_startup_ui(status, len(new_items))
        
        # 3. 상세 탭(StartupFrame) 업데이트
        # (StartupFrame에 있던 run_check 대신 여기서 결과를 바로 주입)
        self.startup_frame.update_ui(status, new_items)

    def create_sidebar_button(self, text, command, row):
        btn = ctk.CTkButton(self.sidebar_frame, text=text, command=command, 
                            font=self.font_bold,
                            fg_color="transparent", text_color=("gray10", "#DCE4EE"), 
                            hover_color=("gray70", "gray30"), anchor="w", height=40)
        btn.grid(row=row, column=0, sticky="ew", padx=10, pady=5)
        return btn

    def select_frame_by_name(self, name):
        for frame in [self.dashboard_frame, self.scan_frame, self.wipe_frame, self.clean_frame, self.startup_frame, self.ai_frame]:
            frame.grid_forget()
        
        if name == "dashboard": self.dashboard_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "scan": 
            self.scan_frame.grid(row=0, column=1, sticky="nsew")
            self.scan_frame.reset_ui()
        elif name == "wipe": self.wipe_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "clean": self.clean_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "startup": self.startup_frame.grid(row=0, column=1, sticky="nsew")
        elif name == "ai": self.ai_frame.grid(row=0, column=1, sticky="nsew")

    def show_dashboard(self): self.select_frame_by_name("dashboard")
    def show_scan(self): self.select_frame_by_name("scan")
    def show_wipe(self): self.select_frame_by_name("wipe")
    def show_clean(self): self.select_frame_by_name("clean")
    def show_startup(self): self.select_frame_by_name("startup")
    def show_ai(self): self.select_frame_by_name("ai")


# --- 핵심 수정: 클릭 가능한 카드 기능이 추가된 DashboardFrame ---

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
        self.create_clickable_card(1, 0, "🧹 디지털 청소", "1.2GB 정리 가능\n(다운로드 폴더)", "#D35400", f_sub, f_body, command=self.app.show_clean)
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


# --- 나머지 프레임들은 동일 ---

# --- [수정됨] 삭제 로직을 비워둔 ScanFrame ---
class ScanFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        self.scanner = SensitiveDataScanner()
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
        
        # 프로그레스바 (일단 생성만 해둠)
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)

        self.result_area = ctk.CTkScrollableFrame(self, label_text="스캔 결과", label_font=f_body)
        self.result_area.pack(fill="both", expand=True, padx=20, pady=20)

    def reset_ui(self):
        self.is_scanning = False
        self.cached_results = []
        self.current_alert_count = 0
        
        self.btn_start.configure(state="normal", text="스캔 시작")
        self.lbl_status.configure(text="준비됨")
        
        # 리셋 시 프로그레스바 숨기기
        self.progress.set(0)
        self.progress.pack_forget()
        
        self.var_show_ignored.set(False) 
        
        for widget in self.result_area.winfo_children():
            widget.destroy()

    def start_thread(self):
        if self.is_scanning: return
        self.is_scanning = True
        self.btn_start.configure(state="disabled", text="스캔 중...")
        
        # [수정됨] before 옵션 에러 해결법: "뺐다가 다시 넣기"
        self.result_area.pack_forget()             # 1. 결과창을 잠시 숨김
        self.progress.pack(fill="x", padx=40, pady=5) # 2. 프로그레스바를 넣음 (이러면 맨 아래에 붙음)
        self.result_area.pack(fill="both", expand=True, padx=20, pady=20) # 3. 결과창을 다시 넣음 (바 아래에 붙음)
        
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
            # 에러 발생 시 처리
            print(f"스캔 오류: {e}")
            self.after(0, lambda: self.handle_scan_error(e))

    def handle_scan_error(self, error_msg):
        self.reset_ui() 
        messagebox.showerror("스캔 오류", f"스캔 도중 문제가 발생하여 중단되었습니다.\n\n[에러 내용]\n{error_msg}")

    # --- 아래는 기존과 동일 ---
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

    def request_secure_delete(self, file_path, card_widget):
        messagebox.showinfo("알림", "보안 삭제 모듈 연동 예정")

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
        
        # 완료되면 프로그레스바 숨기기
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
        self.selected_path = None

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

        self.lbl_drop = ctk.CTkLabel(self.drop_zone, text="이곳에 파일을 드래그(옵션)하거나\n아래 버튼으로 파일을 선택하세요",
                                     font=ctk.CTkFont(family="Malgun Gothic", size=16, weight="bold"))
        self.lbl_drop.place(relx=0.5, rely=0.35, anchor="center")

        self.btn_select = ctk.CTkButton(
            self.drop_zone,
            text="📁 파일 선택하기",
            font=f_body,
            height=42,
            command=self.pick_file
        )
        self.btn_select.place(relx=0.5, rely=0.62, anchor="center")

        # 선택된 파일 표시
        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.pack(fill="x", padx=20, pady=(6, 0))

        ctk.CTkLabel(path_row, text="선택된 파일:", font=f_body).pack(side="left")
        self.entry_path = ctk.CTkEntry(path_row, placeholder_text="파일을 선택하세요", font=f_body)
        self.entry_path.pack(side="left", fill="x", expand=True, padx=(10, 10))
        self.entry_path.configure(state="disabled")

        self.btn_clear = ctk.CTkButton(path_row, text="지우기", width=90, fg_color="#555555",
                                       font=f_body, command=self.clear_file)
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
    
    def on_drop_files(self, files: list[str]):
        # files가 비었으면 그냥 종료(방어)
        if not files:
            return

        first = files[0]

        # 폴더/파일 모두 들어올 수 있음. 일단은 파일만 받는 구조로 처리
        from pathlib import Path
        p = Path(first)

        if p.is_dir():
            self.lbl_status.configure(text="폴더가 드롭됐어요. 현재는 파일만 지원합니다.")
            return

        if not p.exists():
            self.lbl_status.configure(text="드롭된 경로를 찾을 수 없어요.")
            return

        self.set_selected_file(str(p))

    def set_selected_file(self, path: str):
        self.selected_path = path

        self.entry_path.configure(state="normal")
        self.entry_path.delete(0, "end")
        self.entry_path.insert(0, path)
        self.entry_path.configure(state="disabled")

        self.lbl_status.configure(text="파일 선택됨 (드롭)")
        self.progress.set(0)




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
        self.selected_path = None
        self.entry_path.configure(state="normal")
        self.entry_path.delete(0, "end")
        self.entry_path.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="준비됨")

    def pick_file(self):
        if self.is_wiping:
            messagebox.showinfo("알림", "삭제 진행 중에는 변경할 수 없습니다.")
            return
        path = filedialog.askopenfilename()
        if path:
            self.set_path(path)

    # ---------- Workflow ----------
    def confirm_and_start(self):
        if self.is_wiping:
            return

        path = (self.selected_path or "").strip()
        if not path:
            messagebox.showwarning("안내", "먼저 삭제할 파일을 선택하세요.")
            return

        if not os.path.isfile(path):
            messagebox.showwarning("안내", "일반 파일만 삭제할 수 있습니다.")
            return

        # 확인 팝업
        ok = messagebox.askyesno(
            "정말 영구 삭제할까요?",
            "⚠️ 이 작업은 되돌릴 수 없습니다.\n\n"
            "3-pass(0→1→난수) 덮어쓰기 후 파일을 삭제합니다.\n"
            "진행하시겠습니까?"
        )
        if not ok:
            return

        # 시작
        self.is_wiping = True
        self.btn_run.configure(state="disabled")
        self.btn_select.configure(state="disabled")
        self.btn_clear.configure(state="disabled")
        self.progress.set(0)
        self.lbl_status.configure(text="삭제 준비 중...")

        threading.Thread(target=self._wipe_thread, args=(path,), daemon=True).start()

    def _wipe_thread(self, path: str):
        # stage -> 화면 표시용
        stage_map = {
            "PASS1_ZERO": "PASS 1/3: 0으로 덮는 중",
            "PASS2_ONE": "PASS 2/3: 1로 덮는 중",
            "PASS3_RANDOM": "PASS 3/3: 난수로 덮는 중",
        }

        def progress_cb(written, total, stage):
            pct = 0 if total == 0 else (written / total)
            text = stage_map.get(stage, stage)
            self.after(0, lambda: self._update_progress(pct, text))

        status, detail = self.wiper.wipe_file(path, progress_cb=progress_cb)

        self.after(0, lambda: self._finish(status, detail))

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
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        ctk.CTkLabel(self, text="🧹 디지털 찌꺼기 청소", font=f_title).pack(pady=20, padx=20, anchor="w")
        ctk.CTkLabel(self, text="총 2.5GB의 불필요한 파일 정리 가능", font=f_body, text_color="#F39C12").pack(pady=10)
        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.pack(fill="both", expand=True, padx=20, pady=10)
        for i in range(10):
            chk = ctk.CTkCheckBox(self.list_frame, text=f"오래된_과제파일_{i}.pdf", font=f_body)
            chk.pack(anchor="w", pady=5, padx=10)
            chk.select()
        ctk.CTkButton(self, text="정리하기", height=45, font=f_body, fg_color="#27AE60").pack(fill="x", padx=40, pady=20)

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