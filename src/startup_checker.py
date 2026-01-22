# src/startup_checker.py
import winreg
import json
import os

class StartupMonitor:
    def __init__(self, db_file="startup_snapshot.json"):
        self.db_file = db_file
        self.registry_path = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def get_current_startup_programs(self):
        """현재 레지스트리에 등록된 시작 프로그램 목록을 가져옵니다."""
        programs = {}
        try:
            # 윈도우 레지스트리 열기 (HKEY_CURRENT_USER)
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path, 0, winreg.KEY_READ)
            
            # 등록된 값들을 하나씩 읽어옴
            i = 0
            while True:
                try:
                    name, path, _ = winreg.EnumValue(key, i)
                    programs[name] = path
                    i += 1
                except OSError:
                    break # 더 이상 읽을 값이 없으면 종료
            winreg.CloseKey(key)
        except Exception as e:
            print(f"레지스트리 접근 오류: {e}")
            return None
            
        return programs

    def check_for_changes(self):
        """
        저장된 스냅샷과 현재 상태를 비교합니다.
        return: (상태코드, 새로운_프로그램_리스트)
        상태코드: "SAFE", "WARNING", "FIRST_RUN"
        """
        current_progs = self.get_current_startup_programs()
        if current_progs is None:
            return "ERROR", []

        # 1. 저장된 파일이 없으면 (최초 실행) -> 현재 상태 저장하고 종료
        if not os.path.exists(self.db_file):
            self.save_snapshot(current_progs)
            return "FIRST_RUN", []

        # 2. 저장된 파일 불러오기
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                saved_progs = json.load(f)
        except:
            # 파일 깨졌으면 다시 저장
            self.save_snapshot(current_progs)
            return "FIRST_RUN", []

        # 3. 비교 로직 (새로 추가된 것 찾기)
        new_items = []
        for name, path in current_progs.items():
            if name not in saved_progs:
                new_items.append({"name": name, "path": path})

        # 4. 결과 반환
        if new_items:
            # 변경사항이 있으면 사용자에게 알리기 위해 저장하지 않음 (사용자가 확인 후 저장하도록 유도 가능)
            # 여기서는 편의상 감지 후 바로 갱신하지 않고 경고만 줌
            return "WARNING", new_items
        else:
            # 변동 없으면 최신 상태로 갱신 (삭제된 게 있을 수 있으니)
            self.save_snapshot(current_progs)
            return "SAFE", []

    def save_snapshot(self, data):
        """현재 상태를 JSON 파일로 저장"""
        try:
            with open(self.db_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"저장 오류: {e}")
    
    def approve_new_program(self, name, path):
        try:
            # 1. 기존 스냅샷 불러오기
            with open(self.db_file, "r", encoding="utf-8") as f:
                saved_progs = json.load(f)
            
            # 2. 승인된 프로그램 추가
            saved_progs[name] = path
            
            # 3. 저장 (이제 이 프로그램은 '정상'으로 인식됨)
            self.save_snapshot(saved_progs)
            return True
        except Exception as e:
            print(f"승인 오류: {e}")
            return False

# 테스트용 코드 (이 파일을 직접 실행했을 때만 동작)
if __name__ == "__main__":
    monitor = StartupMonitor()
    status, new_items = monitor.check_for_changes()
    print(f"상태: {status}")
    if new_items:
        print("새로 발견된 항목:", new_items)