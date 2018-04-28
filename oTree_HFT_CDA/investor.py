import websocket
try:
    import thread
except ImportError:
    import _thread as thread
import sys
import pandas as pd
import logging
import json
from time import sleep
import datetime


file = 'last-investor-log.txt'
logging.basicConfig(level=logging.INFO,
        format='%(asctime)s %(name)-6s %(levelname)s: %(message)s',
        datefmt='%m-%d %H:%M:%S',
        filename=file,
        filemode='w')

logger = logging.getLogger(__name__)


class Investor(object):

    def __init__(self, group_id, filename):
        self.group_id = group_id
        self.filename = filename
        self.url = 'ws://127.0.0.1:8000/hft_investor/'

    def read(self):
        """
        read arrival side&time
        store as (time, side) tuples
        """
        arrive_times = pd.read_csv(self.filename)
        first_arv = int(arrive_times.loc[0, 'time'])
        arrive_times['time'] = arrive_times['time'].diff()
        arrive_times.loc[0, 'time'] = first_arv
        time_side_tuples = list(arrive_times.itertuples(index=False, name=None))
        self.data = time_side_tuples
        logging.info('Read data.')

    def add_ws(self):
        """
        Websocket to connect to the experiment
        """
        def on_message(ws, message):
            print(message)

        def on_error(ws, error):
            print(error)

        def on_close(ws):
            print ("closed")

        def on_open(ws):
            def run(*args):
                """
                Implements investor behaviour
                """
                for t, side in self.data:
                    logging.info('Start wait: ' + custom_time())
                    sleep(t)
                    logging.info('End wait: ' + custom_time())
                    ws.send(json.dumps({'side': side}))
                ws.close()
            thread.start_new_thread(run, ())

        ws = websocket.WebSocketApp(self.url + self.group_id + '/',
                                    on_message = on_message,
                                    on_error = on_error,
                                    on_close = on_close)
        ws.on_open = on_open
        self.ws = ws


def custom_time():
    return datetime.datetime.now().strftime('%e %b %y-%H:%M:%S.%f')
    

def main():
    logging.info('Investor active: ' + custom_time())
    investor = Investor(sys.argv[1], sys.argv[2])
    investor.read()
    investor.add_ws()
    logging.info('Websocket added: ' + custom_time())
    investor.ws.run_forever()


if __name__ == '__main__':
    main()
