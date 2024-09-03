import sys
import os
from datetime import date, datetime

class Log:
    def __init__(self, args):
        self.args = args
        self.path = os.path.join(args['path'], 'caption')
        self.log_dir = 'Logs'
        self.filename = f'speech{'-' + args["lang"] + '-' if args['lang'] else "-"}{args["model_name"]}'
        self.file = None

    def set_path(self, path):
        self.path = path

    def set_log_dir(self, log_dir):
        self.log_dir = log_dir

    def set_filename(self, filename):
        self.filename = filename

    def create_log_dir(self):
        log_dir_path = os.path.join(self.path, self.log_dir)
        if not os.path.exists(log_dir_path):
            os.makedirs(log_dir_path)

    def create_log_file(self):
        self.create_log_dir()
        today = date.today()
        now = datetime.now()
        formatted_date = today.strftime("%d-%m-%Y")
        formatted_time = now.strftime("%H:%M:%S")
        weekday = now.strftime("%A")
        log_file_path = os.path.join(self.path, self.log_dir, f"{formatted_date}_{self.filename}.log")
        if os.path.exists(log_file_path):
            self.file = open(log_file_path, 'a')
            self.file.write(f"\n{formatted_time} Rerun\n")
        else:
            self.file = open(log_file_path, 'w')
            self.file.write(f"{weekday} {formatted_date} {formatted_time}\n")
            self.file.write(f"Args: {self.args}\n")

    def write_log(self, message):
        if not self.file:
            raise ValueError("Log file has not been created")

        current_time = datetime.now().strftime("%H:%M:%S")
        self.file.write(f"{current_time} ({message})\n")
        self.file.flush()

    def close_log_file(self):
        if self.file:
            self.file.close()
            self.file = None