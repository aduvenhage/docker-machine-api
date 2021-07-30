
import logging
import time

from cl_api import DockerMachine


def test_api():
    logging.basicConfig(level=20)
    logger = logging.getLogger(__name__)

    dm = DockerMachine(name='raytracer',
                       cwd='../',
                       config={
                            'driver': 'digitalocean', 
                            'digitalocean-image': 'ubuntu-18-04-x64', 
                            'digitalocean-access-token': '916d25ba891f579dfe4085f7bff379230705dae1a800bd58b3234508d9745ee7',
                            'engine-install-url': 'https://releases.rancher.com/install-docker/19.03.9.sh'
                       })

    while True:
        try:
            text = dm._stdout_queue.get(block=False)
            logger.info(text)
        except Exception:
            pass

        try:
            text = dm._stderr_queue.get(block=False)
            logger.error(text)
        except Exception:
            pass

        time.sleep(0.1)


if __name__ == "__main__":
    test_api()
