"""
Logging utilities for the application
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output"""
    
    # Color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green  
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m'      # Reset
    }
    
    def format(self, record):
        # Add color
        if record.levelname in self.COLORS:
            record.levelname = f"{self.COLORS[record.levelname]}{record.levelname}{self.COLORS['RESET']}"
        
        return super().format(record)

def setup_logger(name: str = "CapCutGenerator", 
                level: int = logging.INFO, 
                log_to_file: bool = False,
                log_dir: str = "logs") -> logging.Logger:
    """Setup application logger"""
    
    logger = logging.getLogger(name)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
        
    logger.setLevel(level)
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_formatter = ColoredFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_to_file:
        try:
            # Create logs directory
            log_path = Path(log_dir)
            log_path.mkdir(exist_ok=True)
            
            # Create log file with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_file = log_path / f"capcut_generator_{timestamp}.log"
            
            file_handler = logging.FileHandler(log_file, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)  # Log everything to file
            file_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            logger.addHandler(file_handler)
            
            logger.info(f"Logging to file: {log_file}")
            
        except Exception as e:
            logger.warning(f"Could not setup file logging: {e}")
    
    return logger

def get_logger(name: str) -> logging.Logger:
    """Get logger for specific module"""
    return logging.getLogger(f"CapCutGenerator.{name}")

class LogCapture:
    """Capture logs for GUI display"""
    
    def __init__(self, logger: logging.Logger, level: int = logging.INFO):
        self.logger = logger
        self.level = level
        self.messages = []
        self.handler = None
        
    def start_capture(self):
        """Start capturing log messages"""
        self.handler = LogCaptureHandler(self.messages)
        self.handler.setLevel(self.level)
        
        # Use simple formatter for GUI
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', 
                                    datefmt='%H:%M:%S')
        self.handler.setFormatter(formatter)
        
        self.logger.addHandler(self.handler)
        
    def stop_capture(self):
        """Stop capturing log messages"""
        if self.handler:
            self.logger.removeHandler(self.handler)
            self.handler = None
            
    def get_messages(self) -> list:
        """Get captured messages"""
        return self.messages.copy()
        
    def clear_messages(self):
        """Clear captured messages"""
        self.messages.clear()

class LogCaptureHandler(logging.Handler):
    """Custom handler to capture log messages in memory"""
    
    def __init__(self, messages_list: list):
        super().__init__()
        self.messages = messages_list
        
    def emit(self, record):
        try:
            msg = self.format(record)
            self.messages.append(msg)
            
            # Limit message history to prevent memory issues in case of extreme bursts
            # Increased from 1000 to 50000 to support long subtitle projects
            if len(self.messages) > 50000:
                self.messages = self.messages[-40000:]  # Keep last 40000 messages
                
        except Exception:
            self.handleError(record)

class ProgressLogger:
    """Logger for progress tracking"""
    
    def __init__(self, total_steps: int, logger: Optional[logging.Logger] = None):
        self.total_steps = total_steps
        self.current_step = 0
        self.logger = logger or get_logger("Progress")
        self.start_time = datetime.now()
        
    def step(self, message: str = ""):
        """Increment progress and log"""
        self.current_step += 1
        percentage = (self.current_step / self.total_steps) * 100
        
        elapsed = datetime.now() - self.start_time
        
        if self.current_step == self.total_steps:
            self.logger.info(f"✅ Progress: {percentage:.1f}% - {message} - COMPLETED in {elapsed}")
        else:
            # Estimate time remaining
            if self.current_step > 0:
                time_per_step = elapsed.total_seconds() / self.current_step
                remaining_steps = self.total_steps - self.current_step
                estimated_remaining = remaining_steps * time_per_step
                
                self.logger.info(f"📊 Progress: {percentage:.1f}% - {message} - "
                               f"ETA: {estimated_remaining:.1f}s")
            else:
                self.logger.info(f"📊 Progress: {percentage:.1f}% - {message}")
    
    def reset(self, new_total: int = None):
        """Reset progress counter"""
        if new_total:
            self.total_steps = new_total
        self.current_step = 0
        self.start_time = datetime.now()

# Convenience functions
def log_function_call(logger: logging.Logger):
    """Decorator to log function calls"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            logger.debug(f"Calling {func.__name__} with args={len(args)}, kwargs={list(kwargs.keys())}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"Function {func.__name__} completed successfully")
                return result
            except Exception as e:
                logger.error(f"Function {func.__name__} failed with error: {e}")
                raise
        return wrapper
    return decorator

def log_execution_time(logger: logging.Logger):
    """Decorator to log function execution time"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start_time = datetime.now()
            try:
                result = func(*args, **kwargs)
                execution_time = datetime.now() - start_time
                logger.info(f"Function {func.__name__} executed in {execution_time.total_seconds():.2f}s")
                return result
            except Exception as e:
                execution_time = datetime.now() - start_time
                logger.error(f"Function {func.__name__} failed after {execution_time.total_seconds():.2f}s: {e}")
                raise
        return wrapper
    return decorator