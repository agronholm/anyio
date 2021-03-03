import sys


def process_worker():
    import pickle

    print('READY', flush=True)
    while True:
        try:
            command, *args = pickle.load(sys.stdin.buffer)
        except EOFError:
            return
        except BaseException as exc:
            exception = exc
            status = b'EXCEPTION'
            pickled = pickle.dumps(exc, pickle.HIGHEST_PROTOCOL)
        else:
            if command == 'run':
                func, args, kwargs = args
                exception = retval = None
                try:
                    retval = func(*args, **kwargs)
                except BaseException as exc:
                    exception = exc

                try:
                    if exception is not None:
                        status = b'EXCEPTION'
                        pickled = pickle.dumps(exception, pickle.HIGHEST_PROTOCOL)
                    else:
                        status = b'RETURN'
                        pickled = pickle.dumps(retval, pickle.HIGHEST_PROTOCOL)
                except BaseException as exc:
                    exception = exc
                    status = b'EXCEPTION'
                    pickled = pickle.dumps(exc, pickle.HIGHEST_PROTOCOL)

        sys.stdout.buffer.write(b'%s %d\n' % (status, len(pickled)))
        sys.stdout.buffer.write(pickled)
        sys.stdout.buffer.flush()

        # Respect SIGTERM
        if isinstance(exception, SystemExit):
            raise exception


if __name__ == '__main__':
    process_worker()
