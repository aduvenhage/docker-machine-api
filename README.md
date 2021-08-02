# Docker Machine CLI API for Python
As part of my efforts to learn python I decided to create a docker-machine CLI wrapper that can be used from within Python applications to create and manage remote/cloud VM services using docker-machine.  The wrapper also has support for upping and monitoring services, using docker-compose.

Key features of Python I had to learn:
- calling subprocesses using `Popen`
- multi-threading
- queues
- file streams

## Docker Machine
Docker-machine works well to provision remote VMs since it hides much of the boilerplate effort required to create a remote machine, manage keys and create a basic image with Docker installed.  All docker-engine settings are managed via environment variables, and it even makes it easy to secure copy and ssh on the remote VM (with the keys stored in the machine environment).  Docker-machine has built-in drivers for a whole range of cloud providers, including Amazon Web Services, Digital Ocean and Google Compute Engine.


### Docker Machine Commands (CLI)
- create VM (ubuntu 18.04 LTS -- Digital Ocean): 
```
docker-machine create --driver digitalocean --digitalocean-image ubuntu-18-04-x64 --digitalocean-access-token=... do01
```
- activate docker env: `eval $(docker-machine env do01) .`
- deactivate docker env: `eval $(docker-machine env -u)`
- ssh into remote machine: `docker-machine ssh do01`
- list machines: `docker-machine ls`
- remove machines: `docker-machine rm do01`
- provision a system: docker-machine (create --> eval ... --> docker-compose up)
- NOTE: Docker containers may not use volumes/shares/mounts. All shared data must be copied by Dockerfile
- NOTE: Digital Ocean VMs have to be in the same data center (in this case sfo2) as their floating IPs


## Build package
From source root `python setup.py sdist`

## Install package
`pip install docker-machine-api-x.x.x.tar.gz` on built package file.

## Python Usage Examples

```
from docker_machine_api.cl_api import DockerMachine


    # create machine API
    dm = DockerMachine(name='raytracer',
                       cwd='../',
                       config={
                            'driver': 'digitalocean', 
                            'digitalocean-image': 'ubuntu-18-04-x64', 
                            'digitalocean-access-token': '....',
                            'engine-install-url': 'https://releases.rancher.com/install-docker/19.03.9.sh'
                       })

    # watch machine output
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

```
