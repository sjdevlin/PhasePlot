
class Singleton(type):
    import threading

    _instances = {}
    _lock = threading.Lock()  # ensures thread safety

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:  # critical section
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]