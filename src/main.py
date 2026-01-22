import customtkinter as ctk
import os

# --- 초기 설정 ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

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
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # 3. 사이드바 (메뉴)
        self.sidebar_frame = ctk.CTkFrame(self, width=200, corner_radius=0)
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
        self.dashboard_frame = DashboardFrame(self, self.font_title, self.font_subtitle, self.font_body, app_instance=self)
        self.scan_frame = ScanFrame(self, self.font_title, self.font_body)
        self.wipe_frame = WipeFrame(self, self.font_title, self.font_body)
        self.clean_frame = CleanFrame(self, self.font_title, self.font_body)
        self.startup_frame = StartupFrame(self, self.font_title, self.font_body)
        self.ai_frame = AIFrame(self, self.font_title, self.font_body)

        self.select_frame_by_name("dashboard")

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
        elif name == "scan": self.scan_frame.grid(row=0, column=1, sticky="nsew")
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
        self.create_clickable_card(0, 0, "⚠️ 개인정보 노출", "3건 발견됨\n(메모장 내 비밀번호)", "#C0392B", f_sub, f_body, command=self.app.show_scan)
        self.create_clickable_card(0, 1, "🔒 보안 삭제 도구", "파일을 안전하게\n파쇄할 준비 완료", "#2980B9", f_sub, f_body, command=self.app.show_wipe)
        self.create_clickable_card(1, 0, "🧹 디지털 청소", "1.2GB 정리 가능\n(다운로드 폴더)", "#D35400", f_sub, f_body, command=self.app.show_clean)
        self.create_clickable_card(1, 1, "✅ 시작 프로그램", "변동 사항 없음\n(부팅 최적화)", "#27AE60", f_sub, f_body, command=self.app.show_startup)
        
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


# --- 나머지 프레임들은 동일 ---

class ScanFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        ctk.CTkLabel(self, text="📄 개인정보 정밀 스캔", font=f_title).pack(pady=20, padx=20, anchor="w")
        self.btn_start = ctk.CTkButton(self, text="내 PC 스캔 시작", height=50, font=f_body, fg_color="#E67E22", hover_color="#D35400")
        self.btn_start.pack(pady=10, fill="x", padx=40)
        self.scroll_frame = ctk.CTkScrollableFrame(self, label_text="검출된 파일 목록", label_font=f_body)
        self.scroll_frame.pack(fill="both", expand=True, padx=20, pady=20)
        for i in range(5):
            row = ctk.CTkFrame(self.scroll_frame)
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=f"C:/Users/User/Desktop/secret_{i}.txt", font=f_body, anchor="w").pack(side="left", padx=10)
            ctk.CTkButton(row, text="삭제", width=60, font=f_body, fg_color="#C0392B").pack(side="right", padx=5)

class WipeFrame(ctk.CTkFrame):
    def __init__(self, master, f_title, f_body):
        super().__init__(master, corner_radius=0, fg_color="transparent")
        ctk.CTkLabel(self, text="🔒 완전 보안 삭제 (디지털 세탁소)", font=f_title).pack(pady=20, padx=20, anchor="w")
        self.drop_zone = ctk.CTkFrame(self, border_width=2, border_color="gray", corner_radius=20, fg_color=("#E0E0E0", "#2B2B2B"))
        self.drop_zone.pack(fill="both", expand=True, padx=40, pady=20)
        ctk.CTkLabel(self.drop_zone, text="이곳에 파일을 드래그하세요", font=f_title).place(relx=0.5, rely=0.4, anchor="center")
        self.btn_select = ctk.CTkButton(self.drop_zone, text="파일 선택하기", font=f_body, command=lambda: print("클릭"))
        self.btn_select.place(relx=0.5, rely=0.6, anchor="center")

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
        ctk.CTkLabel(self, text="🚀 시작 프로그램 감시", font=f_title).pack(pady=20, padx=20, anchor="w")
        self.status_box = ctk.CTkFrame(self, fg_color="#1E8449", corner_radius=10, height=100)
        self.status_box.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(self.status_box, text="✅ 현재 시스템은 안전합니다.", font=ctk.CTkFont(family="Malgun Gothic", size=18, weight="bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(self, text="[수동 관리 가이드]", font=ctk.CTkFont(family="Malgun Gothic", size=16, weight="bold")).pack(pady=(30, 10), anchor="w", padx=20)
        self.txt_guide = ctk.CTkTextbox(self, height=150, font=f_body)
        self.txt_guide.pack(fill="x", padx=20)
        self.txt_guide.insert("0.0", "작업 관리자 -> 시작 앱 탭에서 관리하세요.")
        self.txt_guide.configure(state="disabled")

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