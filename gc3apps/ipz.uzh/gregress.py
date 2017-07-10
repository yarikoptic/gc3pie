#! /usr/bin/env python
#
#   genREM.py -- Front-end script for running ParRecoveryFun Matlab 
#   function with a given combination of reference models.
#
#   Copyright (c) 2015 S3IT, University of Zurich, http://www.s3it.uzh.ch/
#
#   This program is free software: you can redistribute it and/or
#   modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""

It uses the generic `gc3libs.cmdline.SessionBasedScript` framework.
"""

# summary of user-visible changes
__changelog__ = """
  2015-11-17:
  * Initial version
"""
__author__ = 'Sergio Maffioletti <sergio.maffioletti@uzh.ch>'
__docformat__ = 'reStructuredText'
__version__ = '1.0.0'

# run script, but allow GC3Pie persistence module to access classes defined here;
# for details, see: https://github.com/uzh/gc3pie/issues/95
if __name__ == "__main__":
    import gregress
    gregress.GenREMScript().run()

import os
import sys
import time
import tempfile
import re

import shutil
import random
import posix

from pkg_resources import Requirement, resource_filename

import gc3libs
import gc3libs.exceptions
from gc3libs import Application, Run, Task
from gc3libs.cmdline import SessionBasedScript, executable_file, \
    existing_directory
import gc3libs.utils
from gc3libs.quantity import Memory, kB, MB, MiB, GB, Duration, \
    hours, minutes, seconds
from gc3libs.workflow import RetryableTask, StagedTaskCollection, \
    ParallelTaskCollection, SequentialTaskCollection

# Constanst
S0_REMOTE_INPUT_FILENAME = "./input.stata"
S0_REMOTE_OUTPUT_FILENAME = "./output.RData"
RSCRIPT_COMMAND="Rscript --vanilla {src}/script.R {method} {src} {data}"
STATS = ["stat-inertia", "stat-reciprocity", "stat-similarity", "stat-triad", "stat-degree"]
METHODS = ['remdataset', 'merge'] + STATS
S0_OUTPUT=""
S1_OUTPUT=""
S2_OUTPUT=""
REMOTE_RESULT_FOLDER="result"
REMOTE_DATA_FOLDER="data"
REMOTE_SCRIPTS_FOLDER="src"

# Utility methods

## Custom application class
class GenREMDatasetApplication(Application):
    """
    Transform input .stata file into rem DataFrame
    Could run locally provided R is installed.
    """
    application_name = 'genREM'
    
    def __init__(self, method, data_file_list, source_folder, **extra_args):
        
        inputs = dict()

        self.output = extra_args['results']

        for data_file in os.listdir(data_file_list):
            inputs[os.path.join(data_file_list,
                                data_file)] = os.path.join(REMOTE_DATA_FOLDER,
                                                           data_file)

        for script_file in os.listdir(source_folder):
            inputs[os.path.join(source_folder,
                                script_file)] = os.path.join(REMOTE_SCRIPTS_FOLDER,
                                                             os.path.basename(script_file))

        arguments = RSCRIPT_COMMAND.format(method=method,
                                           src=REMOTE_SCRIPTS_FOLDER,
                                           data=REMOTE_DATA_FOLDER)
        
        Application.__init__(
            self,
            arguments = arguments,
            inputs = inputs,
            outputs = [REMOTE_RESULT_FOLDER],
            stdout = 'genREM.log',
            join=True,
            **extra_args)

    def terminated(self):
        """
        Move results to 'result' folder
        """

        if not os.path.isdir(self.output):
            os.makedirs(self.output)
        for data in os.listdir(os.path.join(self.output_dir,
                                            REMOTE_RESULT_FOLDER)):
            shutil.move(os.path.join(self.output_dir,
                                     REMOTE_RESULT_FOLDER,
                                     data),
                        os.path.join(self.output,
                                     data))
        
class GenREMStagedTaskCollection(StagedTaskCollection):
    """
    Stage0: Take input .stata file and convert it into Rem
    Dataframe.
    """
    def __init__(self, data_folder, source_folder, **extra_args):

        self.data_folder = data_folder
        self.source_folder = source_folder
        self.extra = extra_args
        self.s0_outputfolder = os.path.join(extra_args['result'],"S0")
        self.s1_outputfolder = os.path.join(extra_args['result'],"S1")
        self.s2_outputfolder = os.path.join(extra_args['result'],"S2")
        StagedTaskCollection.__init__(self)
            
    def stage0(self):
        """
        Transform input .stata into rem DataFrame by calling
        ENB_RemDatasetApplication.
        """

        extra_args = self.extra.copy()
        extra_args['jobname'] = "remdataset"
        extra_args['output_dir'] = extra_args['output_dir'].replace('NAME', 
                                                                    extra_args['jobname'])
        extra_args['output_dir'] = extra_args['output_dir'].replace('SESSION', 
                                                                    extra_args['jobname'])
        extra_args['output_dir'] = extra_args['output_dir'].replace('DATE', 
                                                                    extra_args['jobname'])
        extra_args['output_dir'] = extra_args['output_dir'].replace('TIME', 
                                                                    extra_args['jobname'])

        # gc3libs.log.debug("Creating Stage0 task for : %s" % os.path.basename(self.input_stata_file))
        extra_args['results'] = self.s0_outputfolder

        return GenREMDatasetApplication("remdataset",self.data_folder,self.source_folder,**extra_args)


    def stage1(self):
        """
        """
        # XXX: add check if stage0 completed properly
        # Stop otherwise
        tasks = []

        for method in STATS:
            extra_args = self.extra.copy()
            extra_args['jobname'] = method
            extra_args['results'] = self.s1_outputfolder
            tasks.append(GenREMDatasetApplication(method,self.s0_outputfolder,self.source_folder,**extra_args))
        return ParallelTaskCollection(tasks)

    def stage2(self):
        """
        """
        extra_args = self.extra.copy()
        extra_args['jobname'] = "merge"
        extra_args['results'] = self.s2_outputfolder
        return GenREMDatasetApplication("merge",self.data_folder,self.source_folder,**extra_args)

        
class GenREMScript(SessionBasedScript):
    """
    For each param file (with '.mat' extension) found in the 'param folder',
    GscrScript extracts the corresponding index (from filename) and searches for
    the associated file in 'data folder'. For each pair ('param_file','data_file'),
    GscrScript generates execution Tasks.
    
    The ``gscr`` command keeps a record of jobs (submitted, executed
    and pending) in a session file (set name with the ``-s`` option); at
    each invocation of the command, the status of all recorded jobs is
    updated, output from finished jobs is collected, and a summary table
    of all known jobs is printed.
    
    Options can specify a maximum number of jobs that should be in
    'SUBMITTED' or 'RUNNING' state; ``gscr`` will delay submission of
    newly-created jobs so that this limit is never exceeded.
    """

    def __init__(self):
        SessionBasedScript.__init__(
            self,
            version = __version__, # module version == script version
            application = Application,
            stats_only_for = Application
            )

    def setup_args(self):

        self.add_param('data_folder', type=existing_directory,
                       help="Location of initial RData file.")

    def setup_options(self):
        """
        """
        self.add_param("-x", "--source", metavar="PATH", 
                       dest="src", default=None,
                       type=existing_directory,
                       help="Location of source R scripts.")
        
        self.add_param("-R", "--results", metavar="PATH", 
                       dest="result", default='results',
                       help="Location of results.")

    def new_tasks(self, extra):
        """
        For each of the network data and for each of the selected benchmarks,
        create a GscrApplication.

        First loop the input files, then loop the selected benchmarks
        """
        extra_args = extra.copy()
        #extra_args.update(self.params.__dict__)
        extra_args['result'] = self.params.result
        return [GenREMStagedTaskCollection(self.params.data_folder,
                                           self.params.src,
                                           **extra_args)]
