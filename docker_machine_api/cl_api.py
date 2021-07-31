import logging
import subprocess
import threading
import time
import os
import queue
import re
from datetime import datetime, timedelta


class DockerMachineError(Exception):
    """
    Exception thrown by machine components.
    """
    def __init__(self, task, message):
        self.task = task
        self.message = message

    def __str__(self):
        return self.message

    def __repr__(self):
        return "task '%s': %s" % (self.task, self.message)


class DockerStreamReader:
    """
    External thread to help pull out text from machine task processes.
    NOTE: this extra thread is required, since reading from STDERR and STDOUT could block.
    """
    ansi_escape = re.compile(r'(\x9B|\x1B\[)[0-?]*[ -\/]*[@-~]')

    def __init__(self, stream_in):
        self._queue = queue.Queue()
        self._stream = stream_in
        self._thread = threading.Thread(target=self._reader_thread, daemon=True)
        self._thread.start()

    def _format_text(self, text):
        """
        Remove ANSI colour codes, etc
        """
        return self.ansi_escape.sub('', text)

    def _reader_thread(self):
        """
        Read all data from stream and add to internal readline queue
        """
        while not self._stream.closed:
            try:
                text = self._stream.readline()
                if text:
                    self._queue.put(self._format_text(text.strip('\n')))
                else:
                    time.sleep(1)  # wait a little if nothing available

            except Exception:
                pass

    def get_line(self):
        """
        Returns next line in reader queue or None.
        """
        try:
            return self._queue.get(block=False)
        except queue.Empty:
            return None

    def wait(self):
        """
        Close stream and wait for thread to stop.
        """
        try:
            self._stream.close()
            self._thread.join(timeout=2)
        except Exception:
            pass


class DockerMachineTask:
    """
    Wrapper for a task process run by machine.
    """
    default_bin = 'docker-machine'
    default_timeout = 540

    def __init__(self, name='', cwd='./', bin=None, cmd='', params=[], timeout=None, allowed_to_fail=False, output_cb=None):
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
        self._timeout = timeout or self.default_timeout
        self._output_cb = output_cb
        if self._output_cb:
            self._output = list()
        else:
            self._output = None

        self._returncode = None
        self._logger = logging.getLogger(self._name)
        self._allowed_to_fail = allowed_to_fail

    def __str__(self):
        return "%s %s: %d" % (self._bin, self._cmd, self._returncode)

    def _process_output(self, stdout_queue, stderr_queue):
        """
        Process all output from stream readers.
        """
        while True:
            stdout = self._stdout_reader.get_line()
            if stdout is not None:
                stdout_queue.put(stdout)
                if self._output is not None:
                    self._output.append(stdout)

            stderr = self._stderr_reader.get_line()
            if stderr is not None:
                stderr_queue.put(stderr)
                if self._output is not None:
                    self._output.append(stderr)

            if not stdout and not stderr:
                break

    def _finish_output(self, stdout_queue, stderr_queue):
        """
        Wait for process to finish and read last bit of output.
        """
        self._process.wait()
        self._stdout_reader.wait()
        self._stderr_reader.wait()
        self._process_output(stdout_queue, stderr_queue)

    def call(self, env, stdout_queue, stderr_queue):
        """
        Call process and block until done.
        """
        args = [self._bin, self._cmd] + self._params
        self._logger.debug("calling <%s> ...", args)

        # call process
        self._process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=self._cwd, text=True)
        self._stdout_reader = DockerStreamReader(self._process.stdout)
        self._stderr_reader = DockerStreamReader(self._process.stderr)
        self._popen_start_time = datetime.now()
        self._popen_timeout = timedelta(seconds=self._timeout)

        while True:
            # poll process for status and output
            self._logger.debug("polling ...")
            self._process_output(stdout_queue, stderr_queue)
            self._returncode = self._process.poll()

            # check process status
            if self._returncode is not None:
                if self._returncode == 0 or self._allowed_to_fail:
                    self._finish_output(stdout_queue, stderr_queue)

                    # success - task callback to process output
                    if self._output_cb:
                        self._output_cb(os.linesep.join(self._output))

                    self._logger.debug("done")
                    break

                else:
                    # failed - exception
                    self._logger.error("failed - return code %s!", self._returncode)
                    raise DockerMachineError(self, 'Task call failed.')

            # check process timeout
            if datetime.now() - self._popen_start_time > self._popen_timeout:
                self._logger.error("timeout!")
                self._process.kill()
                self._finish_output(stdout_queue, stderr_queue)
                raise DockerMachineError(self, 'Task call timeout.')

            time.sleep(1)


class DockerMachine:
    """
    Docker Machine CLI wrapper.
    Manages docker machine provisioning, setup and tasks.
    """
    def __init__(self, name='', cwd='./', config={}):
        self._name = name
        self._cwd = cwd
        self._config = config
        self._logger = logging.getLogger(self._name)

        self._machine_status = ''
        self._machine_ip = ''
        self._machine_env = None
        self._service_logs = None

        self._task_list = queue.Queue()
        self._stdout_queue = queue.Queue()
        self._stderr_queue = queue.Queue()

        threading.Thread(target=self._machine_thread, daemon=True).start() 

        # add first tasks to provision and setup machine
        self.tskProvisionMachine()
        self.tskStartMachine()
        self.tskGetMachineIp()
        self.tskGetMachineEnv()
        self.tskGetMachineStatus()

    def __str__(self):
        return "Docker machine %s, %s, %s" % (self.name(), self.ip(), self.status())

    def _parse_env_text(self, input, env=os.environ.copy()):
        """
        Parse 'export key="value"\n...' type multi-line strings and return updated environment dictionary.
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
        Machine task thread (executes tasks queued with '_add_task').
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
                self._logger.debug("waiting for tasks ...")

    def name(self):
        """
        Returns machine name (read-only)
        """
        return self._name

    def config(self):
        """
        Returns machine config (provides specific provisioning details; read-only)
        """
        return self._config

    def cwd(self):
        """
        Returns local machine services working folder (docker-compose file location; read-only)
        """
        return self._cwd

    def ip(self):
        """
        Returns the IP of the remote machine
        """
        return self._machine_ip

    def env(self):
        """
        Returns the ENV vars of the remote machine
        """
        return self._machine_env

    def status(self):
        """
        Returns the current status of the machine
        """
        return self._machine_status

    def add_task(self, task):
        """
        Machine task execution thread
        """
        self._task_list.put(task)

    def wait(self):
        """
        Blocks caller until all scheduled tasks have finished
        """
        self._task_list.join()

    def tskProvisionMachine(self, allowed_to_fail=True):
        """
        Schedule task to provision remote machine
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

    def tskStartMachine(self, allowed_to_fail=True):
        """
        Schedule task to start remote machine
        """
        self.add_task(DockerMachineTask(name='startMachine',
                                        cwd=self.cwd(),
                                        cmd='start',
                                        params=[self.name()],
                                        allowed_to_fail=allowed_to_fail))

    def tskStopMachine(self):
        """
        Schedule task to stop remote machine
        """
        self.add_task(DockerMachineTask(name='stopMachine',
                                        cwd=self.cwd(),
                                        cmd='stop',
                                        params=[self.name()]))

    def tskKillMachine(self):
        """
        Schedule task to stop remote machine (forces stop)
        """
        self.add_task(DockerMachineTask(name='killMachine',
                                        cwd=self.cwd(),
                                        cmd='kill',
                                        params=[self.name()]))

    def tskRemoveMachine(self):
        """
        Schedule task to completely remove machine locally and remotely
        """
        self.add_task(DockerMachineTask(name='removeMachine',
                                        cwd=self.cwd(),
                                        cmd='rm',
                                        params=[self.name()]))

    def tskGetMachineEnv(self):
        """
        Schedule task to get remote machine environment
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
        Schedule task to get remote machine status
        """
        def cb(text):
            self._machine_status = text

        self.add_task(DockerMachineTask(name='getMachineStatus',
                                        cwd=self.cwd(),
                                        cmd='status',
                                        params=[self.name()],
                                        output_cb=cb))

    def tskGetMachineIp(self):
        """
        Schedule task to get remote machine IP
        """
        def cb(text):
            self._machine_ip = text

        self.add_task(DockerMachineTask(name='getMachineIp',
                                        cwd=self.cwd(),
                                        cmd='ip',
                                        params=[self.name()],
                                        output_cb=cb))

    def tskSecureCopyToMachine(self, src, dst):
        """
        Schedule secure copy task
        """
        self.add_task(DockerMachineTask(name='secureCopy',
                                        cwd=self.cwd(),
                                        cmd='scp',
                                        params=['-r', src, self.name() + ':' + dst]))

    def tskSecureCopyFromMachine(self, src, dst):
        """
        Schedule secure copy task
        """
        self.add_task(DockerMachineTask(name='secureCopy',
                                        cwd=self.cwd(),
                                        cmd='scp',
                                        params=['-r', self.name() + ':' + src, dst]))

    def tskStartServices(self):
        """
        Schedule task to start remote machine services
        """
        self.__addTask(DockerMachineTask(name='startServices',
                                         cwd=self.cwd(),
                                         bin='docker-compose',
                                         cmd='up',
                                         params=['--build', '-d']))

    def tskGetServiceLogs(self):
        """
        Schedule task to get remote machine service logs
        """
        def cb(text):
            self._service_logs = text

        self.add_task(DockerMachineTask(name='getServiceLogs',
                                        cwd=self.cwd(),
                                        bin='docker-compose',
                                        cmd='logs',
                                        params=['--tail=256'],
                                        output_cb=cb))
