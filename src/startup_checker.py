# src/startup_checker.py
import winreg
import json
import os
import psutil
from datetime import datetime

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

    # [✅ 추가된 기능] 시작 프로그램에서 제거하는 함수
    def delete_program(self, program_name):
        """
        레지스트리에서 해당 프로그램을 제거합니다.
        성공 시 True, 실패 시 False 반환
        """
        try:
            # 레지스트리 키 열기 (쓰기 권한 KEY_WRITE 필요)
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.registry_path, 0, winreg.KEY_WRITE)
            
            # 값 삭제
            winreg.DeleteValue(key, program_name)
            winreg.CloseKey(key)
            
            # 스냅샷(DB)에서도 제거하여 동기화
            self._remove_from_snapshot(program_name)
            
            return True, "삭제 성공"
        except FileNotFoundError:
            return False, "이미 삭제되었거나 존재하지 않는 프로그램입니다."
        except PermissionError:
            return False, "권한이 부족합니다. 관리자 권한으로 실행해주세요."
        except Exception as e:
            return False, f"삭제 오류: {str(e)}"

    def _remove_from_snapshot(self, name):
        """내부 DB(json)에서도 삭제"""
        if os.path.exists(self.db_file):
            try:
                with open(self.db_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                if name in data:
                    del data[name]
                    self.save_snapshot(data)
            except:
                pass

    def get_process_status(self, exe_path):
        """
        해당 경로의 프로그램이 실제로 실행 중인지 확인하고,
        실행 중이라면 메모리 사용량을 반환합니다.
        """
        if not exe_path:
            return "정보 없음"
            
        target_name = os.path.basename(exe_path).lower() # 예: kakaotalk.exe
        
        # 현재 실행 중인 모든 프로세스 뒤지기
        for proc in psutil.process_iter(['name', 'memory_info', 'exe']):
            try:
                # 1. 이름으로 1차 비교
                if proc.info['name'] and proc.info['name'].lower() == target_name:
                    mem_mb = proc.info['memory_info'].rss / (1024 * 1024) # MB 단위 변환
                    return f"🟢 실행 중 ({mem_mb:.1f} MB)"
                
                # 2. (정확도 향상) 전체 경로로 2차 비교
                if proc.info['exe'] and os.path.normpath(proc.info['exe']).lower() == os.path.normpath(exe_path).lower():
                    mem_mb = proc.info['memory_info'].rss / (1024 * 1024)
                    return f"🟢 실행 중 ({mem_mb:.1f} MB)"
                    
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
                
        return "⚪ 실행 안 됨 (리소스 0)"