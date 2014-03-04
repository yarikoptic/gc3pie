#! /usr/bin/env python
#
#   gcelljunction.py -- GC3Pie front-end for running the
#   "tricellular_junction" code by T. Aegerter
#
#   Copyright (C) 2014 GC3, University of Zurich
#
#   This program is free software: you can redistribute it and/or modify
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
Front-end script for runniung multiple `tricellular_junction` instances.
It uses the generic `gc3libs.cmdline.SessionBasedScript` framework.

See the output of ``gcelljunction --help`` for program usage instructions.
"""
__version__ = 'development version (SVN $Revision$)'
# summary of user-visible changes
__changelog__ = """
  2014-03-03:
    * Initial release, forked off the ``gmhc_coev`` sources.
"""
__author__ = 'Riccardo Murri <riccardo.murri@uzh.ch>'
__docformat__ = 'reStructuredText'


# run script, but allow GC3Pie persistence module to access classes defined here;
# for details, see: http://code.google.com/p/gc3pie/issues/detail?id=95
if __name__ == '__main__':
    import gcelljunction
    gcelljunction.GCellJunctionScript().run()


# std module imports
import csv
import glob
import os
import re
import sys
import time
from pkg_resources import Requirement, resource_filename

# gc3 library imports
import gc3libs
from gc3libs import Application, Run, Task
from gc3libs.cmdline import SessionBasedScript
from gc3libs.compat._collections import defaultdict
from gc3libs.quantity import Memory, kB, MB, GB, Duration, hours, minutes, seconds


## custom application class

class GCellJunctionApplication(Application):
    """
    Custom class to wrap the execution of the ``tricellular_junction``
    program by T. Aegerter.
    """

    application_name = 'tricellular_junction'

    def __init__(self, sim_no, executable=None, **extra_args):
        wrapper_sh = resource_filename(Requirement.parse("gc3pie"),
                                       "gc3libs/etc/gcelljunction_wrapper.sh")
        inputs = { wrapper_sh:os.path.basename(wrapper_sh) }
        extra_args.setdefault('requested_cores', 1)
        extra_args.setdefault('requested_memory', 4*GB)
        extra_args.setdefault('requested_architecture', Run.Arch.X86_64)
        extra_args.setdefault('requested_walltime', 12*hours)
        # command-line parameters to pass to the tricellular_junction_* program
        self.sim_no = sim_no
        if executable is not None:
            # use the specified executable
            exename = os.path.basename(executable)
            executable_name = './' + exename
            inputs[executable] = exename
            exe_opts = ['-x', executable_name]
        else:
            # assume one is installed in the VM
            executable_name = 'tricellular_junctions'
            exe_opts = [ ]
        Application.__init__(
            self,
            arguments=['./' + os.path.basename(wrapper_sh), '-d', '--'] + exe_opts + [ sim_no ],
            inputs = inputs,
            outputs = gc3libs.ANY_OUTPUT,
            stdout = 'tricellular_junctions.log',
            join=True,
            **extra_args)


## main script class

class GCellJunctionScript(SessionBasedScript):
    """
Read the specified INPUT ``.csv`` files and submit jobs according
to the content of those files.  Job progress is monitored and, when a
job is done, its ``data/`` and ``data4/`` output directories are
retrieved back into the same directory where the executable file is
(this can be overridden with the ``-o`` option).

The ``gcelljunction`` command keeps a record of jobs (submitted, executed
and pending) in a session file (set name with the ``-s`` option); at
each invocation of the command, the status of all recorded jobs is
updated, output from finished jobs is collected, and a summary table
of all known jobs is printed.  New jobs are added to the session if
new input files are added to the command line.

Options can specify a maximum number of jobs that should be in
'SUBMITTED' or 'RUNNING' state; ``gcelljunction`` will delay submission of
newly-created jobs so that this limit is never exceeded.
    """

    def __init__(self):
        SessionBasedScript.__init__(
            self,
            version = __version__, # module version == script version
            input_filename_pattern = '*.csv',
            application = GCellJunctionApplication,
            # only display stats for the top-level policy objects
            # (which correspond to the processed files) omit counting
            # actual applications because their number varies over
            # time as checkpointing and re-submission takes place.
            stats_only_for = GCellJunctionApplication,
            )


    def setup_options(self):
        self.add_param("-x", "--executable", metavar="PATH",
                       dest="executable", default=None,
                       help="Path to the `tricellular_junctions` executable file.")


    def make_directory_path(self, pathspec, jobname):
        # XXX: Work around SessionBasedScript.process_args() that
        # apppends the string ``NAME`` to the directory path.
        # This is really ugly, but the whole `output_dir` thing needs to
        # be re-thought from the beginning...
        if pathspec.endswith('/NAME'):
            return pathspec[:-len('/NAME')]
        else:
            return pathspec


    def new_tasks(self, extra):
        # how many iterations are we already computing (per parameter set)?
        iters = defaultdict(int)
        for task in self.session:
            name, instance = task.jobname.split('#')
            iters[name] = max(iters[name], int(instance))

        for path in self.params.args:
            if path.endswith('.csv'):
                try:
                    inputfile = open(path, 'r')
                except (OSError, IOError), ex:
                    self.log.warning("Cannot open input file '%s': %s: %s",
                                     path, ex.__class__.__name__, str(ex))
                try:
                    # the `csv.sniff()` function is confused by blank and comment lines,
                    # so we need to filter the input to build a correct sample
                    sample_lines = [ ]
                    while len(sample_lines) < 5:
                        line = inputfile.readline()
                        # exit at end of file
                        if line == '':
                            break
                        # ignore comment lines as they confuse `csv.sniff`
                        if line.startswith('#') or line.strip() == '':
                            continue
                        sample_lines.append(line)
                    csv_dialect = csv.Sniffer().sniff(str.join('', sample_lines))
                    self.log.debug("Detected CSV delimiter '%s'", csv_dialect.delimiter)
                except csv.Error:
                    # in case of any auto-detection failure, fall back to the default
                    self.log.warning("Could not determine field delimiter in file '%s',"
                                     " assuming it's a comma character (',').",
                                     path)
                    csv_dialect = 'excel'
                inputfile.seek(0)
                for lineno, row in enumerate(csv.reader(inputfile, csv_dialect)):
                    # ignore blank and comment lines (those that start with '#')
                    if len(row) == 0 or row[0].startswith('#'):
                        continue
                    try:
                        (replicates, sim_no) = row
                    except ValueError:
                        self.log.error("Wrong format in line %d of file '%s':"
                                       " need 2 comma-separated values, (no. of replicates and `SimNo`)"
                                       " but actually got %d ('%s')."
                                       " Ignoring input line, fix it and re-run.",
                                       lineno+1, path, len(row), str.join(',', (str(x) for x in row)))
                        continue # with next `row`
                    # extract parameter values
                    try:
                        iterno = int(replicates)
                        sim_no = int(sim_no)
                    except ValueError, ex:
                        self.log.warning("Ignoring line '%s' in input file '%s': %s",
                                         str.join(',', row), path, str(ex))
                        continue
                    basename = ('tricellular_junction_%d' % (sim_no,))

                    # prepare job(s) to submit
                    if (iterno > iters[basename]):
                        self.log.info(
                                "Requested %d iterations for %s: %d already in session, preparing %d more",
                                iterno, basename, iters[basename], iterno - iters[basename])
                        for iter in range(iters[basename]+1, iterno+1):
                            kwargs = extra.copy()
                            base_output_dir = kwargs.pop('output_dir', self.params.output)
                            jobname=('%s#%d' % (basename, iter))
                            yield GCellJunctionApplication(
                                sim_no,
                                executable=self.params.executable,
                                jobname=jobname,
                                output_dir=os.path.join(base_output_dir, jobname),
                                **kwargs)

            else:
                self.log.error("Ignoring input file '%s': not a CSV file.", path)