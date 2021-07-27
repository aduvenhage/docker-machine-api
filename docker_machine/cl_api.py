import logging
import subprocess
import threading
import time
import os
import queue
import re

from datetime import datetime, timedelta


class DockerMachineError(Exception):
    def __init__(self, task, message):
        self.task = task
        self.message = message

    def __str__(self):
        return self.message

    def __repr__(self):
        return "task '%s': %s" % (self.task, self.message)


class DockerStreamReader:
    """
    External thread to help pull out text from task process.
    """
    def __init__(self, queue_out, stream_in):
        self.queue = queue_out
        self._stream = stream_in
        self._thread = threading.Thread(target=self._reader_thread, daemon=True).start()

    def _format_text(self, text):
        return self.ansi_escape.sub('', text)

    def _reader_thread(self):
        while not self._stream.closed:
            try:
                text = self._stream.readLine()
                self.queue.put(self._format_text(text))
            except Exception:
                pass

    def wait(self):
        self._thread.join()


class DockerMachineTask:
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')
    default_bin = 'docker-machine'

    def __init__(self, name='', cwd='./', bin=None, cmd='', params=[], timeout=540, allowed_to_fail=False, output_cb=None):
        """
        :param name: task name
        :param cwd: working directry (docker-compose root)
        :param cmd: first argument
        :param params: command arguments
        :param env: environment used for sub-process call
        :param timeout: seconds to wait for sub-process call to complete
        :param callback: func(task_output_text)
        """
        self._name = name
        self._cwd = cwd
        self._bin = bin or self.default_bin
        self._cmd = cmd
        self._params = params
        self._timeout = timeout
        self._output_cb = output_cb
        self._returncode = None
        self._output = list()
        self._logger = logging.getLogger(self._name)
        self._allowed_to_fail = allowed_to_fail

    def __str__(self):
        return "%s %s: %d" % (self._bin, self._cmd, self._returncode)

    def call(self, env, stdout_queue, stderr_queue):
        # start process
        args = [self._bin, self._cmd] + self._params
        self._logger.info("calling <%s> ...", args)

        process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self._cwd, text=True)
        self._stdout_reader = DockerStreamReader(stdout_queue, process.stdout)
        self._stderr_reader = DockerStreamReader(stderr_queue, process.stderr)
        self._popen_start_time = datetime.now()
        self._popen_timeout = timedelta(seconds=self._timeout)

        while True:
            # check for process return or timeout
            self._logger.info("polling ...")
            self._returncode = process.poll()

            if self._returncode is not None:
                if self._returncode == 0 or self._allowed_to_fail:
                    # success - task callback to process output
                    if self._output_cb:
                        self._output_cb(os.linesep.join(self._output))

                    self._logger.info("done")
                    break

                else:
                    # failed - exception
                    self._logger.error("failed - return code %s!", self._returncode)
                    raise DockerMachineError(self, 'Task call failed.')

            if datetime.now() - self._popen_start_time > self._popen_timeout:
                # failed - timeout
                self._logger.error("timeout!")
                process.kill()
                self._stdout_reader.wait()
                self._stderr_reader.wait()
                process.wait()

                raise DockerMachineError(self, 'Task call timeout.')

            time.sleep(1)


class DockerMachine:
    """
    Docker Machine CLI wrapper, with docker-compose service initialisation.

    Methods with names that start with 'tsk', for example 'tskGetMachineStatus()', only schedule a task and returns immediately.

    Task callback (set with setTaskCallback()) will receive (machine=, task=, state=, final=) keyed arguments. 'state' can be
    'start' (called just before taske execution), 'success', or 'error'. 'final' is set to True when this is the last task scheduled. 

    The secure copy tasks can be used to copy files to and from remote machine.
    """
    def __init__(self, name='', cwd='./', config={}):
        self._name = name
        self._cwd = cwd
        self._config = config
        self._logger = logging.getLogger(self._name)

        self._machine_status = ''
        self._machine_ip = ''
        self._machine_env = None
        self._task_list = queue.Queue()
        self._stdout_queue = queue.Queue()
        self._stderr_queue = queue.Queue()

        threading.Thread(target=self._machine_thread, daemon=True).start() 

        # add first tasks to provision, get env & IP and start services
        self.tskProvisionMachine()
        # self.tskStartMachine()
        self.tskGetMachineIp()
        self.tskGetMachineEnv()
        self.tskGetMachineStatus()
        # self.tskStartServices()

    def __str__(self):
        return "Docker machine %s (%s), %s" % (self.name(), self.ip(), self.status())

    def _parse_env_text(self, input, env=os.environ.copy()):
        """
        parse 'export key="value"\n...' type multi-line strings and return updated environment dictionary
        """
        output = env
        lines = input.splitlines()

        for line in lines:
            if line.startswith('export'):
                line = line.lstrip('export')
                words = line.split('=')

                if len(words) == 2:
                    key = words[0].strip(' ')
                    value = words[1].strip('\" ')
                    output[key] = value

        return output

    def _machine_thread(self):
        """
        machine task thread (executes tasks queued with '_addTask')
        """
        while True:
            try:
                task = self._task_list.get(timeout=1)

                try:
                    self._logger.info("calling task '%s' ...", self._name)
                    task.call(env=self._machine_env,
                              stdout_queue=self._stdout_queue,
                              stderr_queue=self._stderr_queue)

                except Exception:
                    self._logger.exception("failed to execute task '%s'!", task._name)
                    raise

                self._task_list.task_done()

            except queue.Empty:
                self._logger.info("waiting for tasks ...")

    def name(self):
        """
        returns machine name (read-only)
        """
        return self._name

    def config(self):
        """
        returns machine config (provides specific provisioning details; read-only)
        """
        return self._config

    def cwd(self):
        """
        returns local machine services working folder (docker-compose file location; read-only)
        """
        return self._cwd

    def ip(self):
        """
        returns the IP of the remote machine
        """
        return self._machine_ip

    def env(self):
        """
        returns the ENV vars of the remote machine
        """
        return self._machine_env

    def status(self):
        """
        returns the current status of the machine
        """
        return self._machine_status

    def add_task(self, task):
        """
        machine task execution thread
        """
        self._task_list.put(task)

    def wait(self):
        """
        blocks caller until all scheduled tasks have finished
        """
        self._task_list.join()

    def tskProvisionMachine(self, allowed_to_fail=True):
        """
        schedule task to provision remote machine
        """
        params = []
        for key, value in self._config.items():
            params.append('--' + key)
            params.append(value)

        params.append(self.name())

        self.add_task(DockerMachineTask(name='provisionMachine',
                                        cwd=self.cwd(),
                                        cmd='create',
                                        params=params,
                                        allowed_to_fail=allowed_to_fail))

    def tskGetMachineEnv(self):
        """
        schedule task to get remote machine environment
        """
        def cb(text):
            self._machine_env = self._parse_env_text(input=text)

        self.add_task(DockerMachineTask(name='getMachineEnv',
                                        cwd=self.cwd(),
                                        cmd='env',
                                        params=[self.name()],
                                        output_cb=cb))

    def tskGetMachineStatus(self):
        """
        schedule task to get remote machine status
        """
        def cb(text):
            self._machine_status = text.strip('\n')

        self.add_task(DockerMachineTask(name='getMachineStatus',
                                        cwd=self.cwd(),
                                        cmd='status',
                                        params=[self.name()],
                                        output_cb=cb))

    def tskGetMachineIp(self):
        """
        schedule task to get remote machine IP
        """
        def cb(text):
            self._machine_ip = text.strip('\n')

        self.add_task(DockerMachineTask(name='getMachineIp',
                                        cwd=self.cwd(),
                                        cmd='ip',
                                        params=[self.name()],
                                        output_cb=cb))


"""        
        
    # schedule task to start remote machine 
    def tskStartMachine(self):
        self.__addTask(DockerMachineTask(name='startMachine', cwd=self.__cwd, cmd='start', params=[self.__name]))

    # schedule task to stop remote machine 
    def tskStopMachine(self):
        self.__addTask(DockerMachineTask(name='stopMachine', cwd=self.__cwd, cmd='stop', params=[self.__name]))

    # schedule task to stop remote machine (forces stop)
    def tskKillMachine(self):
        self.__addTask(DockerMachineTask(name='killMachine', cwd=self.__cwd, cmd='kill', params=[self.__name]))

    # schedule task to completely remove machine locally and remotely
    def tskRemoveMachine(self):
        self.__addTask(DockerMachineTask(name='removeMachine', cwd=self.__cwd, cmd='rm', params=[self.__name]))

    # schedule task to start remote machine services
    def tskStartServices(self):
        self.__addTask(DockerMachineTask(name='startServices', cwd=self.__cwd, bin='docker-compose', cmd='up', params=['--build', '-d']))

    # schedule task to get remote machine service logs
    def tskGetServiceLogs(self):
        # NOTE: callback runs on machine task thread
        def cb(task):
            if task.returncode == 0:
                with self.__machineLock:
                    self.__serviceLogs = task.stdout.decode('ascii')

        self.__addTask(DockerMachineTask(name='getServiceLogs', cwd=self.__cwd, bin='docker-compose', cmd='logs', params=['--tail=256'], callback=cb))

    # schedule secure copy task
    def tskSecureCopyToMachine(self, src, dst):
        self.__addTask(DockerMachineTask(name='secureCopy', cwd=self.__cwd, cmd='scp', params=['-r', src, self.__name + ':' + dst]))

    # schedule secure copy task
    def tskSecureCopyFromMachine(self, src, dst):
        self.__addTask(DockerMachineTask(name='secureCopy', cwd=self.__cwd, cmd='scp', params=['-r', self.__name + ':' + src, dst]))

"""


def test():
    logging.basicConfig(level=10)
    logger = logging.getLogger(__name__)

    dm = DockerMachine(name='raytracer',
                       cwd='../',
                       config={ 
                            'driver': 'digitalocean', 
                            'digitalocean-image': 'ubuntu-18-04-x64', 
                            'digitalocean-access-token': 'e177d1ce7be4e9950a2686f0a7dee3f8b653b74e177cfe5b4f86d8f3d9ecabdf',
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


if __name__ == "__main__":
    test()
