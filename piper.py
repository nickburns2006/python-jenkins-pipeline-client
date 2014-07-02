from datetime import datetime,timedelta
import json
import requests

class JenkinsPipeline(object):
    def __init__(self, jenkins_url, pipeline_name, auth=None,
            max_state_cache=timedelta(seconds=10)):
        self.jenkins_url = jenkins_url

        if self.jenkins_url[-1] == "/":
            self.jenkins_url = self.jenkins_url[0:-1]

        self.pipeline_name = pipeline_name
        self._pipeline = {}
        self.max_state_cache = max_state_cache
        self._state = []
        self.state_last_updated = datetime(1983,9,2)

        self.auth = auth

    @property
    def pipeline_url(self):
        """
        This will build the pipeline api url from the passed in pipeline index
        or name.

        """

        return "{!s}/view/{!s}/api/json".format(self.jenkins_url, self.pipeline_name)

    def get_last_build_url(self, job_url):
        """
        This takes in the job url from the pipeline list of jobs and appends
        the appropriate url data to the end to get the lastBuild api url.
        """

        return "{!s}lastBuild/api/json".format(job_url)

    def get_job_build_url(self, job_url):
        """
        This takes in the job url from the pipeline list of jobs and appends
        the appropriate url data to the end to get the build trigger url
        """

        return "{!s}build".format(job_url)

    def run_request(self, url, method="get"):
        """
        This takes in a url and optional method (default: get) that will then
        run the request against that url. If the auth object was set at
        instantiation, it will attach that to the auth as basic authentication.
        """

        method = getattr(requests, method, "get")
        kwargs = {}

        if self.auth is not None:
            kwargs['auth'] = self.auth

        return method(url, **kwargs)

    @property
    def pipeline(self):
        """
        This grabs the pipeline data from the jenkins server. It caches it
        locally once it's been called once to speed things up.
        """

        if not self._pipeline:
            response = self.run_request(self.pipeline_url)

            self._pipeline = response.json()

        return self._pipeline

    @property
    def jobs(self):
        """
        This retrieves the list of jobs for a particular pipeline.
        """

        pipeline_data = self.pipeline

        return pipeline_data.get('jobs', [])

    @property
    def is_state_stale(self):
        """
        This will compare the cached state time with current time and determine
        if it needs refreshed.

        """

        return not self._state or datetime.now() - self.state_last_updated > self.max_state_cache

    @property
    def state(self):
        """
        This will determine the latest state of the pipeline by looking at each
        of the jobs and determining which one was last run. It returns a list
        of the latest state of each of the jobs that have been run for this
        pipeline instance.
        """

        if not self.is_state_stale:
            return self._state

        job_data = []

        for job in self.jobs:
            url = self.get_last_build_url(job['url'])
            response = self.run_request(url)

            # Failed/Not Run job
            if 200 > response.status_code or response.status_code >= 400:
                break

            try:
                last_job_time = int(job_data[-1]['timestamp'])
            except IndexError:
                last_job_time = 0

            job = response.json()

            if int(job['timestamp']) >= last_job_time:
                job_data.append(job)

        self._state = job_data
        self.state_last_updated = datetime.now()

        return self._state

    @property
    def latest_step(self):
        """
        This will fetch the last step that ran (in any status) on the pipeline.

        """

        try:
            return self.state[-1]
        except IndexError:
            return None

    @property
    def is_complete(self):
        """
        This returns a boolean value indicating whether or not the pipeline has
        run all the way to the end successfully.
        """

        state = self.state

        if len(state) != len(self.jobs) or state[-1]['result'] != 'SUCCESS':
            return False
        else:
            return True

    @property
    def is_waiting_manual_trigger(self):
        """
        This returns a boolean value indicating that the pipeline is waiting on
        the next step to be triggered manually.
        """

        return not self.is_complete and self.latest_step['result'] == 'SUCCESS'

    @property
    def next_step(self):
        """
        This calculates which step is next in the pipeline.
        """

        if not self.is_complete:
            try:
                return self.jobs[len(self.state)]
            except IndexError:
                pass

    def build_job(self, job):
        """
        This expects a job object dictionary and will trigger the build on it.
        """

        url = self.get_job_build_url(job['url'])

        return self.run_request(url, 'post')

    def run(self):
        """
        This will trigger the first job in the pipeline which means that the
        state will be reset.
        """

        return self.build_job(self.jobs[0])


    def trigger_manual_step(self):
        """
        This will check to make sure that the next job in the pipeline steps is
        a manual trigger and is waiting on user interaction and then will kick
        it off.

        """

        if self.is_waiting_manual_trigger:
            return self.build_job(self.next_step)
