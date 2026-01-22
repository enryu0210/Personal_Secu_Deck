import customtkinter as ctk
import threading
import os
import sys

# 상위 폴더(src 밖)의 모듈을 찾기 위한 경로 설정
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))
from src.scanner import SensitiveDataScanner

class ScanFrame(ctk.CTkFrame):
    def __init__(self, master, **kwargs):
        super().__init__(master, **kwargs)
        self.scanner = SensitiveDataScanner()
        self.is_scanning = False
        self.setup_ui()

    def setup_ui(self):
        # 타이틀
        ctk.CTkLabel(self, text="🕵️ 개인정보 스캐너 (개발자 모드)", font=("Malgun Gothic", 24, "bold")).pack(pady=20)
        
        # 시작 버튼
        self.btn_start = ctk.CTkButton(self, text="스캔 시작", height=50, fg_color="#E67E22", 
                                     font=("Malgun Gothic", 16, "bold"), command=self.start_thread)
        self.btn_start.pack(fill="x", padx=50, pady=10)

        # 상태 메시지 & 프로그레스바
        self.lbl_status = ctk.CTkLabel(self, text="준비됨", font=("Malgun Gothic", 14))
        self.lbl_status.pack(pady=5)
        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", padx=50, pady=5)

        # 결과창 (스크롤 가능)
        self.result_area = ctk.CTkScrollableFrame(self, label_text="스캔 결과")
        self.result_area.pack(fill="both", expand=True, padx=20, pady=20)

    def start_thread(self):
        if self.is_scanning: return
        self.is_scanning = True
        self.btn_start.configure(state="disabled", text="스캔 중...")
        
        # 기존 결과 지우기
        for widget in self.result_area.winfo_children(): widget.destroy()
        
        # 스레드 시작
        threading.Thread(target=self.run_scan, daemon=True).start()

    def run_scan(self):
        # 콜백 함수: 로직이 진행률을 보고하면 UI를 업데이트
        def update_progress(val):
            self.progress.set(val / 100)
            self.lbl_status.configure(text=f"검사 중... {val}%")
        
        results = self.scanner.start_scan(update_progress)
        
        # 완료 처리 (반드시 메인 스레드 예약)
        self.after(0, lambda: self.show_results(results))

    def show_results(self, results):
        self.is_scanning = False
        self.btn_start.configure(state="normal", text="다시 스캔하기")
        
        count = len(results)
        self.lbl_status.configure(text=f"분석 완료! 총 {count}개의 파일이 감지되었습니다.")

        # 기존 결과 지우기
        for widget in self.result_area.winfo_children():
            widget.destroy()

        if not results:
            ctk.CTkLabel(self.result_area, text="안전합니다! 발견된 정보가 없습니다.").pack(pady=20)
            return

        # 위험(danger) 우선 정렬
        results.sort(key=lambda x: 0 if x['detections'][0]['level'] == 'danger' else 1)

        # ---------------------------------------------------------
        # [핵심] 카드 하나를 만드는 내부 함수 (변수 꼬임 방지용)
        # ---------------------------------------------------------
        def create_card(item):
            detection = item['detections'][0]
            file_path = item['file_path']
            risk_level = detection['level']
            full_content = detection['content'].strip()
            
            # 짧은 미리보기 텍스트 (헤더용)
            preview_content = full_content
            if len(preview_content) > 40:
                preview_content = preview_content[:40] + "..."

            # 색상 테마 설정
            if risk_level == 'danger':
                icon = "🚨 위험"
                card_color = "#561818" # 진한 빨강
                text_color = "#FF9999"
                reason_text_color = "#FFCCCC"
            else:
                icon = "⚠️ 의심"
                card_color = "#564618" # 진한 노랑
                text_color = "#F5D0A9"
                reason_text_color = "#FFF5E0"

            # 1. 카드 전체 프레임 (여기에 헤더와 본문이 다 들어감)
            card = ctk.CTkFrame(self.result_area, fg_color=card_color)
            card.pack(fill="x", pady=3, padx=5)

            # 2. 헤더 프레임 (항상 보이는 부분)
            header = ctk.CTkFrame(card, fg_color="transparent")
            header.pack(fill="x", padx=5, pady=5)

            # 아이콘
            ctk.CTkLabel(header, text=icon, width=60, font=("Malgun Gothic", 12, "bold"), 
                         text_color=text_color).pack(side="left", anchor="n")

            # 정보 텍스트 영역
            info_frame = ctk.CTkFrame(header, fg_color="transparent")
            info_frame.pack(side="left", fill="both", expand=True, padx=5)

            ctk.CTkLabel(info_frame, text=os.path.basename(file_path), font=("Malgun Gothic", 13, "bold"), 
                         anchor="w", text_color="white").pack(fill="x")
            
            # 탐지 내용 (짧게) - 클릭하면 펼쳐진다는 힌트 추가
            lbl_preview = ctk.CTkLabel(info_frame, text=f"🔎 {preview_content}", 
                                     font=("Malgun Gothic", 11), text_color=reason_text_color, anchor="w")
            lbl_preview.pack(fill="x")

            # 3. 상세 내용 프레임 (처음엔 숨겨둠!)
            detail_frame = ctk.CTkFrame(card, fg_color="#2B2B2B", corner_radius=5)
            # 주의: 여기서 .pack()을 하지 않습니다. 나중에 버튼 누르면 pack 할 예정.

            # 상세 내용 안에 들어갈 긴 텍스트
            ctk.CTkLabel(detail_frame, text=f"[전체 경로]\n{file_path}\n\n[탐지된 전체 문장]\n{full_content}", 
                         font=("Malgun Gothic", 12), text_color="white", justify="left", anchor="w",
                         wraplength=400).pack(padx=10, pady=10, fill="x")

            # -----------------------------------------------------
            # [기능] 펼치기/접기 토글 함수
            # -----------------------------------------------------
            def toggle_details():
                if detail_frame.winfo_viewable():
                    detail_frame.pack_forget() # 숨기기
                    btn_toggle.configure(text="▼")
                else:
                    detail_frame.pack(fill="x", padx=10, pady=(0, 10)) # 보이기
                    btn_toggle.configure(text="▲")

            # 버튼 영역 (헤더 오른쪽)
            btn_frame = ctk.CTkFrame(header, fg_color="transparent")
            btn_frame.pack(side="right")

            # 토글 버튼 (화살표)
            btn_toggle = ctk.CTkButton(btn_frame, text="▼", width=30, height=30, fg_color="transparent", 
                                       border_width=1, border_color=text_color, text_color=text_color,
                                       command=toggle_details)
            btn_toggle.pack(side="right", padx=2)

            # 기능 버튼들
            ctk.CTkButton(btn_frame, text="삭제", width=50, height=30, fg_color="#C0392B", hover_color="#922B21",
                          command=lambda p=file_path, c=card: self.secure_delete(p, c)).pack(side="right", padx=2)
            
            ctk.CTkButton(btn_frame, text="열기", width=50, height=30, fg_color="#3498DB",
                          command=lambda p=file_path: os.startfile(os.path.dirname(p))).pack(side="right", padx=2)

        # ---------------------------------------------------------
        # 반복문으로 카드 생성 실행
        # ---------------------------------------------------------
        for item in results:
            create_card(item)
            
# --- 단독 실행 테스트용 ---
if __name__ == "__main__":
    app = ctk.CTk()
    app.geometry("600x500")
    app.title("Feature 1: Scanner Test")
    ScanFrame(app).pack(fill="both", expand=True)
    app.mainloop()