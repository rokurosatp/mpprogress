"""subprocess等で複数プロセスにまたがるプログラムを利用するときに進捗を伝達するためのライブラリ
"""
import os
import datetime
import time
import struct
import mmap
import tempfile

def get_temp_path(name):
    tempdir = tempfile.gettempdir()
    return os.path.join(tempdir, "mpprogress.{}.tmp".format(name))

def timedelta_seconds(delta: datetime.timedelta):
    return delta.seconds + delta.microseconds / 1000000

def from_time_pair(ordinal: int, seconds: float):
    dt = datetime.datetime.fromordinal(ordinal)
    dt += datetime.timedelta(seconds=seconds)

def to_time_pair(dt: datetime.datetime):
    ordinal = dt.toordinal()
    dt2 = datetime.datetime.fromordinal(ordinal)
    seconds = timedelta_seconds(dt - dt2)
    return (ordinal, seconds)

class NameProvider:
    """一意な名前を設定するためのクラス
    """
    def __init__(self):
        self.name_table = set()
    def get_name(self, base_name):
        """get progress names
        the function called when the progress started
        """
        if base_name not in self.name_table:
            self.name_table.add(base_name)
            return base_name
        for i in range(1000):
            name = "{}{}".format(base_name, i)
            if name not in  self.name_table:
                self.name_table.add(name)
                return name
        raise RuntimeError("Name provider index exceeds limit")
    def erase_name(self, name):
        """erase progress names
        the function called when the progress completed
        """
        self.name_table.discard(name)

class ProgressInfo:
    """進捗情報をデータに保存するクラス
    NOTE:
        進捗の時間はプロセス起動時基準なのでプロセスを超えてカウントを行うようなケースには対応していない
    """
    def __init__(self):
        self.closed = 0
        self.min_value = 0
        self.max_value = 0
        self.count = 0
        self.start_time = datetime.datetime.now()
        self.last_update = datetime.datetime.now()
        self.now_update = datetime.datetime.now()
        self.update_time_average = 0.0

    def update_value(self, count):
        last_count = self.count
        self.last_update = self.now_update
        self.count = count
        self.now_update = datetime.datetime.now()
        proceed_count = self.count - last_count
        time_diff = self._get_time_diff()
        if proceed_count > 0:
            self.update_time_average += (time_diff / proceed_count - self.update_time_average) / self.count

    def _get_relative_count(self):
        return self.count - self.min_value

    def _get_time_diff(self):
        return timedelta_seconds(self.now_update - self.last_update)

    def _get_percentage(self):
        return 100 * (self.count - self.min_value) / (self.max_value - self.min_value)

    def _get_remaining_time(self):
        return (self.max_value - self.count) * self.update_time_average

    def _get_elapsed(self):
        return timedelta_seconds(self.now_update - self.start_time)

    def _get_total(self):
        return self.max_value - self.min_value

    def dump_to_bytes(self):
        """バイナリデータに変換
        """
        d_times = tuple(map(to_time_pair, (self.start_time, self.last_update, self.now_update)))
        return struct.pack("@illlidididd",
            self.closed, self.min_value, self.max_value, self.count,
            *d_times[0], *d_times[1], *d_times[2], self.update_time_average
        )

    def close(self):
        self.closed = 1

    def calc_byte_length(self):
        """バイナリにダンプした際のサイズを取得
        """
        return struct.calcsize("@illlidididd")

    def load_from_bytes(self, buffer):
        """バイナリデータからロード
        """
        unpacked = struct.unpack("@illlidididd", buffer)
        (self.closed, self.min_value, self.max_value,
            self.count, d_times, self.update_time_average) = (
                *unpacked[0:4], unpacked[4:10], unpacked[10]
        )
        (self.start_time, self.last_update, self.now_update) = map(
            lambda d:from_time_pair(*d), (d_times[0:2], d_times[2:4], d_times[4:6])
        )
        

    elapsed = property(_get_elapsed)
    eta = property(_get_remaining_time)
    time_diff = property(_get_time_diff)
    percentage = property(_get_percentage)
    total_count = property(_get_total)
    relative_count = property(_get_relative_count)

class ProgressView:
    """メモリマップファイルを利用した進捗内容の共有インタフェース
    書き込みを行うインタフェースにはwritableを設定しておく
    """
    def __init__(self, name, writable=False):
        self.name = name
        self.tempname_path = get_temp_path(self.name)
        self.writable = writable

    def update(self, progress: ProgressInfo):
        """メモリマップファイルに書き込んで共有する進捗内容を更新する
        """
        if not self.writable:
            raise ValueError("the view is not writable")
        with open(self.tempname_path, "r+b") as fp:
            with mmap.mmap(fp.fileno(), 0) as mm:
                mm.write(progress.dump_to_bytes())

    def initialize(self):
        with open(self.tempname_path, "wb") as fp:
            for i in range(ProgressInfo().calc_byte_length()):
                fp.write(b" ")

    def delete(self):
        if not self.writable:
            raise ValueError("the view is not writable")
        os.remove(self.tempname_path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.writable:
            self.delete()

    def get(self):
        """共有された進捗内容をメモリマップファイルから読み取る
        """
        try:
            with open(self.tempname_path, "rb") as fp:
                with mmap.mmap(fp.fileno(), 0, access=mmap.ACCESS_READ) as mm:
                    progress = ProgressInfo()
                    progress.load_from_bytes(mm.read(progress.calc_byte_length()))
        except OSError:
            return None
        except ValueError:
            return None
        return progress

    def exists(self):
        return os.path.exists(self.tempname_path)
        
class ProgressBase:
    def __init__(self, min_value=0, max_value=0):
        pass
    def update(self, count):
        pass
    def finish(self):
        pass

class MultiprocessedProgress(ProgressBase):
    """
    """
    def __init__(self, name, min_value=0, max_value=0):
        super().__init__(min_value=min_value, max_value=max_value)
        self.name = main_name_provider.get_name(name)
        self.interface = ProgressView(self.name, writable=True)
        self.info = ProgressInfo()
        self.info.min_value = min_value
        self.info.max_value = max_value
        self.info.count = min_value
        self.interface.initialize()
        self.interface.update(self.info)

    def update(self, count):
        self.info.update_value(count)
        self.interface.update(self.info)

    def finish(self):
        self.interface.delete()
        self.info.close()

    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_value, traceback):
        self.finish()

main_name_provider = NameProvider()