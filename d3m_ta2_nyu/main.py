'''Entrypoints for the TA2.

This contains the multiple entrypoints for the TA2, that get called from
different commands. They spin up a D3mTa2 object and use it.
'''

import logging
import os
import sys
from d3m_ta2_nyu.ta2 import D3mTa2


logger = logging.getLogger(__name__)


TA2_API_HOST = '[::]'
TA2_API_PORT = os.environ['PORT']

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s:%(levelname)s:AlphaD3M:%(name)s:%(message)s')


def main_search():
    setup_logging()
    timeout = None
    output_folder = None

    if 'D3MTIMEOUT' in os.environ:
        timeout = int(os.environ.get('D3MTIMEOUT'))

    if 'D3MOUTPUTDIR' in os.environ:
        output_folder = os.environ['D3MOUTPUTDIR']

    logger.info('Config loaded from environment variables D3MOUTPUTDIR=%r D3MTIMEOUT=%r',
                os.environ['D3MOUTPUTDIR'], os.environ.get('D3MTIMEOUT'))

    ta2 = D3mTa2(output_folder)
    dataset = '/input/TRAIN/dataset_TRAIN/datasetDoc.json'
    problem_path = '/input/TRAIN/problem_TRAIN/problemDoc.json'
    ta2.run_search(dataset, problem_path=problem_path, timeout=timeout)


def main_serve(argv):
    setup_logging()
    port = None
    output_folder = None

    if 'D3MOUTPUTDIR' in os.environ:
        output_folder = os.environ['D3MOUTPUTDIR']

    logger.info('Config loaded from environment variables D3MOUTPUTDIR=%r D3MTIMEOUT=%r',
                os.environ['D3MOUTPUTDIR'], os.environ.get('D3MTIMEOUT'))

    ta2 = D3mTa2(output_folder)
    ta2.run_server(TA2_API_PORT)

if __name__ == '__main__':
    main_serve(sys.argv[1:])
