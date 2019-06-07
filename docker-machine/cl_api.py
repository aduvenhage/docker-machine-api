

import subprocess
import threading
import time
import os




class DockerMachineTask:
    name = ''               # task name
    cwd = ''                # binary working directory
    bin = ''                # docker binary (docker-machine, docker-compose, etc.)
    cmd = ''                # first argument on binary
    params = []             # command arguments
    timeout = 540           # seconds to wait for sub-process call to complete
    env = None              # environment used for sub-process call
    stdout = ''             # sub-process output 
    stderr = ''             # sub-process error output
    returncode = 0          # sub-process return code
    callback = None         # function 'func(DockerMachineTask)' called when process ends

    def __init__(self, name='', cwd='./', bin='docker-machine', cmd='', params=[], callback=lambda task: None):
        self.name = name
        self.cwd = cwd
        self.bin = bin
        self.cmd = cmd
        self.params = params
        self.callback = callback

    # return string representation of this task
    def __str__(self):
        return "Task '%s' (%s %s: %d)" % (self.name, self.bin, self.cmd, self.returncode)

    # cb (callback) is called when a sub-process stops
    def call(self, env=None, cb=None):
        self.env = env.copy() if env else None        
        args = [self.bin, self.cmd] + self.params
        process = None

        try:
            process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=self.env, cwd=self.cwd)
            self.stdout, self.stderr = process.communicate(timeout=self.timeout)
            self.returncode = process.returncode
            self.callback(self)

        except TimeoutError as e:
            process.kill()
            self.stdout, self.stderr = process.communicate()
            self.returncode = process.returncode
            self.callback(self)

            raise Exception("Remote machine task '%s %s' failed. %s" % (self.bin, self.cmd, str(e)))

        if self.returncode != 0:
            raise Exception("Remote machine task '%s %s' failed. %s" % (self.bin, self.cmd, self.stderr.decode('ascii')))

        return self.stdout.decode('ascii')



class DockerMachine:
    '''
    Docker Machine CLI wrapper, with docker-compose service initialisation.

    Methods with names that start with 'tsk', for example 'tskGetMachineStatus()', only schedule a task and returns immediately.

    Task callback (set with setTaskCallback()) will receive (machine=, task=, state=, final=) keyed arguments. 'state' can be
    'start' (called just before taske execution), 'success', or 'error'. 'final' is set to True when this is the last task scheduled. 

    The secure copy tasks can be used to copy files to and from remote machine. 

    '''

    __name = ''                   # name of machine
    __cwd = ''                    # working folder for docker-compose operations
    __config = {}                 # docker machine specific configuration
    
    __taskList = []               # list of tasks to perform on machine thread
    __currentTask = None          # current/last task
    __taskHistory = []            # tasks already executed
    __taskCallback = None         # user set task activity callback

    __machineLock = None          # sub-process thread lock
    __machineStatus = ''          # machine status
    __machineIp = ''              # machine remote ip
    __machineEnv = None           # machine environment
    __machineStatus = ''          # current machine status
    __machineErrorMsg = None      # current/last task error msg
    
    __serviceLogs = ''            # machine service logs


    # provision remote machine and start service(s)
    def __init__(self, name='', cwd='./', config={}, taskCb=None):
        # init machine properties
        self.__name = name
        self.__cwd = cwd
        self.__config = config
        self.__machineLock = threading.Lock()
        self.setTaskCallback(taskCb)

        # start machine thread
        threading.Thread(target=self.__machineThread, daemon=True).start() 

        # add first tasks to provision, get env & IP and start services
        self.tskProvisionMachine()
        self.tskStartMachine()
        self.tskGetMachineIp()
        self.tskGetMachineEnv()
        self.tskGetMachineStatus()
        self.tskStartServices()

    # return string representation of this machine
    def __str__(self):
        return "Docker machine %s (%s), %s" % (self.__name, self.ip(), self.status())

    # parse 'export key="value"\n...' type multi-line strings and return updated environment dictionary
    def __parseEnvText(self, input='', env=os.environ.copy()):

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

    # machine task execution thread
    def __addTask(self, task=None):
        # lock task list and add new function
        with self.__machineLock:
            self.__taskList.append(task)

    # machine task thread (executes tasks queued with '__addTask')
    def __machineThread(self):
        while True:
            newTask = False
            taskListEmpty = False

            # lock task list and take out first task
            # NOTE: only takes a new task if previous one completed successfully
            with self.__machineLock:
                if not self.__currentTask:
                    if len(self.__taskList) > 0:
                        self.__machineErrorMsg = None
                        self.__currentTask = self.__taskList[0]
                        self.__taskList.pop(0)
                        self.__taskHistory.append(self.__currentTask)
                        newTask = self.__currentTask != None

                    else:
                        self.__currentTask = None

                taskListEmpty = len(self.__taskList) == 0

            # execute task
            if newTask:
                try:
                    self.__taskCallback(machine=self, task=self.__currentTask, state='start', final=taskListEmpty) 
                    self.__currentTask.call(env=self.__machineEnv)
                    self.__taskCallback(machine=self, task=self.__currentTask, state='success', final=taskListEmpty) 
                    self.__currentTask = None

                except Exception as e:
                    with self.__machineLock:
                        self.__machineErrorMsg = "Machine (%s) task '%s' failed. %s" % (self.__name, self.__currentTask.name, str(e))

                    self.__taskCallback(machine=self, task=self.__currentTask, state='error', final=taskListEmpty) 

            time.sleep(1)



    # blocks caller until all scheduled tasks have finished or an error ocurred
    def wait(self):
        while True:
            with self.__machineLock:
                # wait until task list is empty and current task is done
                if len(self.__taskList) == 0 and not self.__currentTask:
                    return None

                if self.__machineErrorMsg:
                    return self.__machineErrorMsg

            time.sleep(1)

    # clear errors and allow machine to continue
    def clearErrors(self):
        with self.__machineLock:
            self.__currentTask = None
            self.__machineErrorMsg = None
    
    # Sets callback for all task actions (see class comments)
    def setTaskCallback(self, cb):
        if cb:
            self.__taskCallback = cb
        else:
            self.__taskCallback = lambda **kwargs: None


    # schedule task to provision remote machine
    def tskProvisionMachine(self):
        params = []
        for key, value in self.__config.items():
            params.append('--' + key)
            params.append(value)
        
        params.append(self.__name)

        self.__addTask(DockerMachineTask(name='provisionMachine', cwd=self.__cwd, cmd='create', params=params))

    # schedule task to get remote machine environment
    def tskGetMachineEnv(self):
        # NOTE: callback runs on machine task thread
        def cb(task):
            if task.returncode == 0:
                with self.__machineLock:
                    self.__machineEnv = self.__parseEnvText(input=task.stdout.decode('ascii'))

        self.__addTask(DockerMachineTask(name='getMachineEnv', cwd=self.__cwd, cmd='env', params=[self.__name], callback=cb))
        
    # schedule task to get remote machine status
    def tskGetMachineStatus(self):
        # NOTE: callback runs on machine task thread
        def cb(task):
            if task.returncode == 0:
                with self.__machineLock:
                    self.__machineStatus = task.stdout.decode('ascii').strip('\n')

        self.__addTask(DockerMachineTask(name='getMachineStatus', cwd=self.__cwd, cmd='status', params=[self.__name], callback=cb))
        
    # schedule task to get remote machine IP
    def tskGetMachineIp(self):
        # NOTE: callback runs on machine task thread
        def cb(task):
            if task.returncode == 0:
                with self.__machineLock:
                    self.__machineIp = task.stdout.decode('ascii').strip('\n')

        self.__addTask(DockerMachineTask(name='getMachineIp', cwd=self.__cwd, cmd='ip', params=[self.__name], callback=cb))
        
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



    # returns machine name (read-only)
    def name(self):
        return self.__name

    # returns machine config (provides specific provisioning details; read-only)
    def config(self):
        return self.__config

    # returns local machine services working folder (docker-compose file location; read-only)
    def cwd(self):
        return self.__cwd

    # returns the IP of the remote machine
    def ip(self):
        with self.__machineLock:
            return self.__machineIp

    # returns the ENV vars of the remote machine
    def env(self):
        with self.__machineLock:
            return self.__machineEnv

    # returns the current status of the machine
    def status(self):
        with self.__machineLock:
            return self.__machineStatus

    # returns the current/last task error message of the machine
    def errors(self):
        with self.__machineLock:
            return self.__machineErrorMsg

    # returns the current/last task error message of the machine
    def history(self):
        output = []

        with self.__machineLock:
            for task in self.__taskHistory:
                output.append(str(task))

        return output

    # returns the remote machine service logs
    def logs(self):
        with self.__machineLock:
            return self.__serviceLogs


