# modules/extractor/dictionary_manager.py

import os
import json
from pathlib import Path

class DictionaryManager:
    """
    Quản lý từ điển sửa lỗi cho module trích xuất phụ đề.
    Cho phép tạo, lưu và áp dụng các bộ từ điển riêng cho từng bộ phim.
    """
    def __init__(self, dictionaries_folder=None):
        """
        Khởi tạo DictionaryManager.
        
        Args:
            dictionaries_folder (str, optional): Thư mục chứa các từ điển. 
                                               Nếu None, sẽ sử dụng thư mục mặc định.
        """
        if dictionaries_folder is None:
            # Tạo thư mục mặc định trong cùng thư mục với module
            base_dir = Path(os.path.dirname(os.path.abspath(__file__)))
            self.dictionaries_folder = base_dir / "dictionaries"
        else:
            self.dictionaries_folder = Path(dictionaries_folder)
            
        # Đảm bảo thư mục tồn tại
        os.makedirs(self.dictionaries_folder, exist_ok=True)
        
        # Danh sách các từ điển đã tải
        self.loaded_dictionaries = {}
        
        # Từ điển đang được sử dụng
        self.current_dictionary = None
        self.current_dictionary_name = None
        
    def create_dictionary(self, dictionary_name):
        """
        Tạo một từ điển mới.
        
        Args:
            dictionary_name (str): Tên của từ điển mới.
            
        Returns:
            bool: True nếu tạo thành công, False nếu từ điển đã tồn tại.
        """
        dictionary_path = self.dictionaries_folder / f"{dictionary_name}.json"
        
        if dictionary_path.exists():
            return False
        
        # Tạo từ điển trống
        empty_dict = {}
        
        with open(dictionary_path, 'w', encoding='utf-8') as f:
            json.dump(empty_dict, f, ensure_ascii=False, indent=4)
        
        # Tải từ điển vừa tạo
        self.loaded_dictionaries[dictionary_name] = {}
        self.current_dictionary = {}
        self.current_dictionary_name = dictionary_name
        
        return True
    
    def load_dictionary(self, dictionary_name):
        """
        Tải một từ điển từ file.
        
        Args:
            dictionary_name (str): Tên của từ điển cần tải.
            
        Returns:
            bool: True nếu tải thành công, False nếu từ điển không tồn tại.
        """
        dictionary_path = self.dictionaries_folder / f"{dictionary_name}.json"
        
        if not dictionary_path.exists():
            return False
        
        try:
            with open(dictionary_path, 'r', encoding='utf-8') as f:
                dictionary = json.load(f)
            
            self.loaded_dictionaries[dictionary_name] = dictionary
            self.current_dictionary = dictionary
            self.current_dictionary_name = dictionary_name
            
            return True
        except Exception as e:
            print(f"Lỗi khi tải từ điển {dictionary_name}: {e}")
            return False
    
    def save_dictionary(self, dictionary_name=None):
        """
        Lưu từ điển hiện tại hoặc từ điển được chỉ định.
        
        Args:
            dictionary_name (str, optional): Tên của từ điển cần lưu. 
                                           Nếu None, sẽ lưu từ điển hiện tại.
                                           
        Returns:
            bool: True nếu lưu thành công, False nếu có lỗi.
        """
        if dictionary_name is None:
            if self.current_dictionary_name is None:
                return False
            dictionary_name = self.current_dictionary_name
        
        if dictionary_name not in self.loaded_dictionaries:
            return False
        
        dictionary_path = self.dictionaries_folder / f"{dictionary_name}.json"
        
        try:
            with open(dictionary_path, 'w', encoding='utf-8') as f:
                json.dump(self.loaded_dictionaries[dictionary_name], f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"Lỗi khi lưu từ điển {dictionary_name}: {e}")
            return False
    
    def get_all_dictionaries(self):
        """
        Lấy danh sách tất cả các từ điển có sẵn.
        
        Returns:
            list: Danh sách tên các từ điển.
        """
        dictionary_files = list(self.dictionaries_folder.glob("*.json"))
        return [file.stem for file in dictionary_files]
    
    def add_correction(self, wrong_text, correct_text, dictionary_name=None):
        """
        Thêm một cặp sửa lỗi vào từ điển.
        
        Args:
            wrong_text (str): Văn bản sai cần sửa.
            correct_text (str): Văn bản đúng sau khi sửa.
            dictionary_name (str, optional): Tên từ điển cần thêm. 
                                           Nếu None, sẽ thêm vào từ điển hiện tại.
                                           
        Returns:
            bool: True nếu thêm thành công, False nếu có lỗi.
        """
        if dictionary_name is None:
            if self.current_dictionary_name is None:
                return False
            dictionary_name = self.current_dictionary_name
        
        if dictionary_name not in self.loaded_dictionaries:
            if not self.load_dictionary(dictionary_name):
                return False
        
        self.loaded_dictionaries[dictionary_name][wrong_text] = correct_text
        
        if dictionary_name == self.current_dictionary_name:
            self.current_dictionary = self.loaded_dictionaries[dictionary_name]
        
        # Tự động lưu từ điển sau khi thêm
        return self.save_dictionary(dictionary_name)
    
    def remove_correction(self, wrong_text, dictionary_name=None):
        """
        Xóa một cặp sửa lỗi khỏi từ điển.
        
        Args:
            wrong_text (str): Văn bản sai cần xóa.
            dictionary_name (str, optional): Tên từ điển cần xóa. 
                                           Nếu None, sẽ xóa từ từ điển hiện tại.
                                           
        Returns:
            bool: True nếu xóa thành công, False nếu có lỗi hoặc không tìm thấy.
        """
        if dictionary_name is None:
            if self.current_dictionary_name is None:
                return False
            dictionary_name = self.current_dictionary_name
        
        if dictionary_name not in self.loaded_dictionaries:
            if not self.load_dictionary(dictionary_name):
                return False
        
        if wrong_text in self.loaded_dictionaries[dictionary_name]:
            del self.loaded_dictionaries[dictionary_name][wrong_text]
            
            if dictionary_name == self.current_dictionary_name:
                self.current_dictionary = self.loaded_dictionaries[dictionary_name]
            
            # Tự động lưu từ điển sau khi xóa
            return self.save_dictionary(dictionary_name)
        
        return False
    
    def update_correction(self, old_wrong_text, new_wrong_text, new_correct_text, dictionary_name=None):
        """
        Cập nhật một cặp sửa lỗi trong từ điển.
        
        Args:
            old_wrong_text (str): Văn bản sai cũ cần thay thế.
            new_wrong_text (str): Văn bản sai mới.
            new_correct_text (str): Văn bản đúng mới.
            dictionary_name (str, optional): Tên từ điển cần cập nhật. 
                                           Nếu None, sẽ cập nhật từ điển hiện tại.
                                           
        Returns:
            bool: True nếu cập nhật thành công, False nếu có lỗi.
        """
        if dictionary_name is None:
            if self.current_dictionary_name is None:
                return False
            dictionary_name = self.current_dictionary_name
        
        if dictionary_name not in self.loaded_dictionaries:
            if not self.load_dictionary(dictionary_name):
                return False
        
        # Kiểm tra xem từ cũ có tồn tại không
        if old_wrong_text not in self.loaded_dictionaries[dictionary_name]:
            return False
        
        # Nếu từ sai mới khác với từ sai cũ, cần xóa từ cũ trước
        if old_wrong_text != new_wrong_text:
            del self.loaded_dictionaries[dictionary_name][old_wrong_text]
        
        # Thêm từ mới
        self.loaded_dictionaries[dictionary_name][new_wrong_text] = new_correct_text
        
        if dictionary_name == self.current_dictionary_name:
            self.current_dictionary = self.loaded_dictionaries[dictionary_name]
        
        # Tự động lưu từ điển sau khi cập nhật
        return self.save_dictionary(dictionary_name)
    
    def apply_corrections(self, text, dictionary_name=None):
        """
        Áp dụng các sửa lỗi từ từ điển vào văn bản.
        
        Args:
            text (str): Văn bản cần sửa.
            dictionary_name (str, optional): Tên từ điển cần áp dụng. 
                                           Nếu None, sẽ áp dụng từ điển hiện tại.
                                           
        Returns:
            str: Văn bản sau khi đã sửa lỗi.
        """
        if dictionary_name is None:
            if self.current_dictionary_name is None:
                return text
            dictionary = self.current_dictionary
        else:
            if dictionary_name not in self.loaded_dictionaries:
                if not self.load_dictionary(dictionary_name):
                    return text
            dictionary = self.loaded_dictionaries[dictionary_name]
        
        corrected_text = text
        for wrong_text, correct_text in dictionary.items():
            corrected_text = corrected_text.replace(wrong_text, correct_text)
        
        return corrected_text