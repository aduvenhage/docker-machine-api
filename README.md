# Docker Machine CLI API for Python
As part of my efforts to learn python I decided to create a docker-machine CLI wrapper that can be used from within Python applications to create and manage remote/cloud VM services using docker-machine.  The wrapper also has support for upping and monitoring services, using docker-compose.

Key features of Python I had to learn:
- calling subprocesses using `Popen`
- multi-threading
- queues
- file streams

*NOTE*: checkout <https://aduvenhage.github.io/raytracer/> for an example of where I use this API to run raytracing in the cloud.

## Docker Machine
Docker-machine works well to provision remote VMs since it hides much of the boilerplate effort required to create a remote machine, manage keys and create a basic image with Docker installed.  All docker-engine settings are managed via environment variables, and it even makes it easy to secure copy and ssh on the remote VM (with the keys stored in the machine environment).  Docker-machine has built-in drivers for a whole range of cloud providers, including Amazon Web Services, Digital Ocean and Google Compute Engine.

### Installing docker-machine
The install on my macbook was straightforward:
- Docker: download docker desktop from https://www.docker.com/products/docker-desktop
- docker-machine: brew install docker-machine, doctl
- create API token: https://cloud.digitalocean.com/account/api/tokens
- login on API: `doctl auth init -t $TOKEN`
- list droplet sizes: `doctl compute size ls`
  for example:
  ```
  Slug                  Memory    VCPUs    Disk    Price Monthly    Price Hourly
  c-4                   8192      4        50      80.00            0.119050
  c-32                  65536     32       400     640.00           0.952380
  ```
- list available regions: `doctl compute region ls`
  for example:
  ```
  nyc1    New York 1         true
  sfo1    San Francisco 1    false
  nyc2    New York 2         false
  ams2    Amsterdam 2        false
  sgp1    Singapore 1        true
  lon1    London 1           true
  nyc3    New York 3         true
  ams3    Amsterdam 3        true
  fra1    Frankfurt 1        true
  tor1    Toronto 1          true
  sfo2    San Francisco 2    true
  blr1    Bangalore 1        true
  sfo3    San Francisco 3    true  
  ```


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



## Build package
From source root `python setup.py sdist`

## Install package
- `pip install docker-machine-api-x.x.x.tar.gz` on built package file, or
- `pip install git+https://github.com/aduvenhage/docker-machine-api` to install directly from github.

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
                       },
                       user_env={...})

    # watch machine output
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

```

## Feature List
- [x] Docker machine task manager
- [x] Tasks to provision, start/stop, get status, etc. 
- [x] sub-process stdout/stderr stream available to user
- [ ] Config options for AWS, GCP and DO