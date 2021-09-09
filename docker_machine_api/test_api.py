
import logging
import time
import os

from cl_api import DockerMachine
from machine_config import DigitalOceanConfig


def start_render_machine(token, scenario):
    logger = logging.getLogger(__name__)
    logger.info("TOKEN %s", token)

    # create new docker machine
    config = DigitalOceanConfig(token=token)
    dm = DockerMachine(name='raytracer',
                       cwd='./../raytracer',
                       config=config.config(),
                       user_env={
                           'SCENARIO': scenario,
                           'OUTPUT': 'raytraced_frame.jpeg',
                           'VOLUME': '/root/output/'
                       })

    dm.tskRunServices()
    dm.tskSecureCopyFromMachine("/root/output/raytraced_frame.jpeg", "raytraced.jpeg")
    dm.tskStopMachine()
    dm.tskKillMachine()
    dm.tskRemoveMachine()
    return dm


if __name__ == "__main__":
    """
    For testing only ...
    """
    logging.basicConfig(level=20)
    logger = logging.getLogger(__name__)

    dm = start_render_machine(os.environ['TOKEN'], 'scene2')

    # wait for rendering to complete
    idle = False
    while dm.busy() or not idle:
        idle = True
        try:
            text = dm._stdout_queue.get(block=False)
            logger.info(text)
            idle = False

        except Exception:
            pass

        try:
            text = dm._stderr_queue.get(block=False)
            logger.error(text)
            idle = False

        except Exception:
            pass

        if idle:
            time.sleep(0.2)
