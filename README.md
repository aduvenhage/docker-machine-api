# Docker Machine CLI API for Python
As part of my efforts to learn python I decided to create a docker-machine CLI wrapper that can be used from within Python applications to create and manage remote/cloud VM services using docker-machine.  The wrapper also has support for upping and monitoring services, using docker-compose.  Sharing this code on GitHub so that peers can review it and also to keep it safe.

## Docker Machine
Docker-machine works well to provision remote VMs since it hides much of the boilerplate effort required to create a remote machine, manage keys and create a basic image with Docker installed.  All docker-engine settings are managed via environment variables, and it even makes it easy to secure copy and ssh on the remote VM (with the keys stored in the machine environment).  Docker-machine has built-in drivers for a whole range of cloud providers, including Amazon Web Services, Digital Ocean and Google Compute Engine.


### Docker Machine Commands
- create VM (ubuntu 18.04 LTS -- Digital Ocean): 
```
docker-machine create --driver digitalocean --digitalocean-image ubuntu-18-04-x64 --digitalocean-access-token=... do01
```
- activate docker env: `eval $(docker-machine env do01) .`
- deactivate docker env: `eval $(docker-machine env -u)`
- ssh into remote machine: `docker-machine ssh do01`
- list machines: `docker-machine ls`
- remove machines: `docker-machine rm do01`
- provision a system: docker-machine (create --> ssh --> docker-compose up)
- NOTE: Docker containers may not use volumes/shares/mounts. All shared data must be copied from Dockerfiles


## Python Usage Examples

```
from docker_machine.cl_api import DockerMachine


# machine test/debug task callback
def taskCb(**kwargs):
    state = kwargs.pop('state', '')
    task = kwargs.pop('task', None)
    machine = kwargs.pop('machine', None)

    if state == 'error':
        print('%s. %s - %s. %s' % (machine, task, state, machine.errors()))
    else:
        print('%s. %s - %s' % (machine, task, state))

# create new docker machine
dm = DockerMachine(name='machine1', 
                    config={ 
                        'driver': 'digitalocean', 
                        'digitalocean-image': 'ubuntu-18-04-x64', 
                        'digitalocean-access-token': '...'
                    },
                    taskCb=taskCb)

# add more tasks
dm.tskGetServiceLogs()

# wait for docker machine tasks to complete
while True:
    msg = dm.wait() 
    if msg:
        dm.clearErrors()
    else:
        break

# print out task history
print('\n'.join(dm.history()))

# print out service logs
print(dm.logs())  """


```
