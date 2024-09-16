import os
from datetime import date, datetime

class Log:
    """A class for logging messages to a file with date management."""

    def __init__(self, args):
        """
        Initializes the Log object.
        
        Args:
            args (dict): Dictionary containing logging parameters.
        """
        self.args = args
        self.path = os.path.join(args['path'], 'caption')
        self.log_dir = 'Logs'
        self.filename = f'speech{'-' + args["lang"] + '-' if args['lang'] else "-"}{args["model_name"]}'
        self.test_name = 'test'
        self.file = None
        self.test = None
        self.current_date = None  # Track the current date
        self.encoding = 'utf-8'  # Specify the encoding
        date = datetime.now().strftime("%d-%m-%Y")

        # Assuming self.path, self.log_dir, and self.filename are already defined
        matching_files = [
            item for item in os.listdir(os.path.join(self.path, self.log_dir))
            if item.startswith(date)
        ]
        # Define the lambda function to find unique parts in file paths
        
        find_unique_parts = lambda path1, path2: (
            (set(part for part in os.path.splitext(os.path.basename(path1))[0].replace('-', '_').replace('+','_').split('_') if part),
            set(part for part in os.path.splitext(os.path.basename(path2))[0].replace('-', '_').replace('+','_').split('_') if part)
            )
        )
        if len(matching_files) > 0:
            for file in matching_files:
                file_path = os.path.join(self.path, self.log_dir, self.filename)
                match_path = os.path.join(self.path, self.log_dir, file)
                if os.path.exists(match_path):        # Process the file since it doesn't exist
                    if file_path != match_path:
                        # Get unique parts
                        unique_parts = find_unique_parts(file_path, match_path)
                        # Calculate unique parts
                        unique_to_file = unique_parts[0] - unique_parts[1]
                        parts = os.path.splitext(os.path.basename(match_path))
                        if len(unique_to_file) < 1 or unique_to_file == set():
                            self.filename = parts[0].split('_')[1]
                            continue
                        #unique_to_match = unique_parts[1] - unique_parts[0]
                        self.filename = parts[0] + '-' + '+'.join(unique_to_file) + parts[1]
                        combined = os.path.join(self.path, self.log_dir, self.filename)
                        os.rename(match_path, combined)
                        time = datetime.now().strftime("%H:%M:%S")
                        self.file = open(combined, 'a', encoding=self.encoding)
                        self.file.write(f'\n{args['model_name']} + {args['lang']}\n{date} {time} :  {args}\n')
        if not self.file:
            self.create_log_file()
    def set_path(self, path):
        """Sets the path for log files."""
        self.path = path

    def set_log_dir(self, log_dir):
        """Sets the directory name for logs."""
        self.log_dir = log_dir

    def set_filename(self, filename):
        """Sets the filename for the log."""
        self.filename = filename

    def create_log_dir(self):
        """Creates the log directory if it does not exist."""
        log_dir_path = os.path.join(self.path, self.log_dir)
        if not os.path.exists(log_dir_path):
            os.makedirs(log_dir_path)

    def create_log_file(self):
        """Creates a new log file for the current date."""
        self.create_log_dir()
        today = date.today()
        now = datetime.now()
        formatted_date = today.strftime("%d-%m-%Y")
        formatted_time = now.strftime("%H:%M:%S")
        weekday = now.strftime("%A")
        log_file_path = os.path.join(self.path, self.log_dir, f"{formatted_date}_{self.filename}.log")

        if self.test_name:
            test_file_path = os.path.join(self.path, self.log_dir, f"{self.test_name}.txt")
            self.test = open(test_file_path, 'w', encoding=self.encoding)
            self.test.write(f"{formatted_date} {formatted_time}\n{self.args}\n")

        if os.path.exists(log_file_path):
            self.file = open(log_file_path, 'a', encoding=self.encoding)
            self.file.write(f"\n{formatted_time} Rerun\n")
        else:
            self.file = open(log_file_path, 'w', encoding=self.encoding)
            self.file.write(f"{weekday} {formatted_date} {formatted_time}\n")
            self.file.write(f"Args: {self.args}\n")

        # Set the current date after creating the log file
        self.current_date = today

    def write_log(self, message, file=None):
        """Writes a message to the log file or a specified file.

        Args:
            message (str): The message to log.
            file (file object, optional): The file to write to. Defaults to self.file.

        Raises:
            ValueError: If the log file has not been created.
            IOError: If there is an issue writing to the log file.
        """
        if file is None:
            file = self.file
        
        if file is None:
            raise ValueError("Log file has not been created")

        # Check if the date has changed
        current_date = date.today()
        if current_date != self.current_date:
            self.close_log_file()  # Close the old log file
            self.create_log_file()  # Create a new log file

        current_time = datetime.now().strftime("%H:%M:%S")
        try:
            file.write(f"{current_time} ({message})\n")
            file.flush()
        except IOError as e:
            raise IOError(f"Error writing to log file: {e}") from e

    def close_log_file(self):
        """Closes the current log file."""
        if self.file:
            self.file.close()
            self.file = None