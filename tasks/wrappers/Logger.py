import logging
import os


def get(name=None) -> logging.Logger:
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s - %(levelname)s - %(message)s')

    log_level = os.environ.get('GOCY_LOG_LEVEL', None)
    logger = logging.getLogger(name)
    if log_level is not None:
        try:
            logger.setLevel(log_level)
        except (TypeError, ValueError) as err:
            print("Invalid log level: {}\n{}".format(log_level, err))

    return logger
