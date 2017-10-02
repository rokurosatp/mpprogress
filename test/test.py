"""動作確認用のテストコード
"""
import argparse
import subprocess
import sys
import shlex
from mpprogress import mpprogress
import mmap
import threading
import time
import datetime

def server_read_sub(name):
    opened = False
    closed = False
    reader = mpprogress.ProgressView(name)
    while not opened or not closed:
        progress = reader.get()
        if progress:
            print("COUNT:{}|ELP:{}|ETA:{:.03f}s".format(
                    "{}/{}({:.02f}%)".format(progress.relative_count, progress.total_count, progress.percentage),
                    time.strftime("%H:%M:%S", time.gmtime(progress.elapsed)),
                    #datetime.timedelta(seconds=
                    #progress.update_time_average,
                    # ),
                    progress.eta
                ))
            opened = True
        else:
            if opened:
                closed = True
        time.sleep(0.05)
    print("読み込みが終了しました")    

def server_main(name):
    print("サーバーです")
    with open("dat/testdata.tmp", "wb") as fp:
        pass
    provider = mpprogress.NameProvider()
    th = threading.Thread(target=server_read_sub, args=(name,), daemon=True)
    th.start()
    test = provider.get_name(name)
    process = subprocess.Popen(shlex.split("python -m test.test -p client -n {}".format(name)))
    result = process.communicate()
    print("joining subprocess")
    th.join(timeout=1.0)

def client_main(name):
        progress = mpprogress.MultiprocessedProgress(name, max_value=100)
        print("クライアントです")
        for i in range(100):
            time.sleep(0.05)
            progress.update(i)
        progress.finish()
        print("書き込みが終了しました")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--process", "-p", choices=("server", "client"))
    parser.add_argument("--name", "-n")
    args = parser.parse_args()

    if args.process == "server":
        server_main(args.name)
    else:
        client_main(args.name)

if __name__ == "__main__":
    main()