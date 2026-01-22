import os
import re

class SensitiveDataScanner:
    def __init__(self):
        # 확장자 목록
        self.target_extensions = ['.txt', '.md', '.py', '.json', '.ini', '.log']
        
        # 정규표현식 패턴
        self.patterns = {
            'password': re.compile(r'(password|pw|비밀번호|pass)\s*[:=]\s*\S+', re.IGNORECASE),
            'phone': re.compile(r'010-\d{4}-\d{4}'),
            'jumin': re.compile(r'\d{6}-[1-4]\d{6}')
        }

    def get_target_directories(self):
        """탐색 경로 설정 (OneDrive 포함)"""
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, 'Desktop'),
            os.path.join(home, 'Documents'),
            os.path.join(home, 'Downloads'),
            os.path.join(home, 'OneDrive', 'Desktop'),
            os.path.join(home, 'OneDrive', 'Documents'),
            os.path.join(home, 'OneDrive', '문서'),
            os.path.join(home, 'OneDrive', '바탕 화면')
        ]
        return [path for path in candidates if os.path.exists(path)]

    def _classify_risk(self, file_path, risk_type):
        """
        위험도 판단 로직 강화판
        """
        # 1. 주민번호/전화번호는 무조건 '위험' (가장 강력한 개인정보)
        if risk_type in ['jumin', 'phone']:
            return 'danger'

        lower_path = file_path.lower()
        file_name = os.path.basename(lower_path)

        # ---------------------------------------------------------
        # [NEW] 2. 개발용 샘플/예시 파일 필터링 (False Positive 1위)
        # config.sample.py, .env.example 등은 가짜 정보임
        # ---------------------------------------------------------
        if 'sample' in file_name or 'example' in file_name or 'template' in file_name:
            return 'warning'

        # ---------------------------------------------------------
        # [NEW] 3. 설명서 파일 필터링
        # readme.md, install.txt 등은 설명문일 확률이 높음
        # ---------------------------------------------------------
        if 'readme' in file_name or 'license' in file_name or 'install' in file_name:
            return 'warning'

        # 4. 게임/앱 설정 및 데이터 파일 (기존 로직 + json/xml 추가)
        suspicious_keywords = ['steam', 'games', 'nexon', 'riot', 'logs', 'config', 'cache']
        suspicious_exts = ['.ini', '.log', '.json', '.xml', '.yaml', '.yml']
        
        if any(key in lower_path for key in suspicious_keywords):
            return 'warning'
        
        if any(lower_path.endswith(ext) for ext in suspicious_exts):
            return 'warning'

        # 5. 그 외(바탕화면의 일반 txt 등)는 진짜 위험할 수 있음
        return 'danger'

    def scan_file(self, file_path):
        detected_items = []
        try:
            # 인코딩 처리
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.readlines()
            except UnicodeDecodeError:
                with open(file_path, 'r', encoding='cp949') as f:
                    content = f.readlines()

            for line_num, line in enumerate(content, 1):
                for risk_type, pattern in self.patterns.items():
                    if pattern.search(line):
                        # 여기서 위험도(level)를 판단합니다.
                        risk_level = self._classify_risk(file_path, risk_type)
                        
                        detected_items.append({
                            'type': risk_type,
                            'level': risk_level,  # <--- 이 부분이 핵심!
                            'line': line_num,
                            'content': line.strip()[:60]
                        })
                        break # 한 줄에 하나 찾으면 스톱
        except Exception:
            return None

        return detected_items if detected_items else None

    def start_scan(self, progress_callback=None):
        # (기존과 동일하여 생략 가능하지만, 전체 복붙 편의를 위해 유지)
        target_dirs = self.get_target_directories()
        risky_files = []
        
        all_files = []
        for path in target_dirs:
            if os.path.exists(path):
                for root, _, files in os.walk(path):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in self.target_extensions):
                            all_files.append(os.path.join(root, file))
        
        total_count = len(all_files)
        if total_count == 0: return []

        for idx, file_path in enumerate(all_files):
            result = self.scan_file(file_path)
            if result:
                risky_files.append({'file_path': file_path, 'detections': result})
            if progress_callback:
                progress_callback(int((idx + 1) / total_count * 100))

        return risky_files