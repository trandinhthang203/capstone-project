import os
import sys

class CustomException(Exception):
    def __init__(self, error_mesage, error_detatil: sys):
        self.error_message = error_mesage
        _, _, exc_tb = error_detatil.exc_info()
        self.line_no = exc_tb.tb_lineno
        self.file_name = exc_tb.tb_frame.f_code.co_filename

    def __str__(self):
        return (
            f"Error occurred in python script [{self.file_name}]"
            f" at line [{self.line_no}]"
            f" with message [{self.error_message}]"
        )
