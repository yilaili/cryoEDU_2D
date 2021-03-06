#!/usr/bin/env python3
import json
import argparse
import os
import sys
import subprocess
from check_if_done import check_state_lsi
import time
import shutil
from write_submit_script_lsi import write_submit_lsi
import re

'''
Submit relion 2D classification job.
Inputs: 1. Path of the *particles.star file from particle extraction,
        2. Name of the 2D classification directory,
        3. Diameter of the mask,
        4. Number of classes,
        5. tau2_fudge,
        6. Whether to do ctf (default is False),
        7. Whether to ignore ctf until first peak (default is False),
        8. zero_mask (default is False).
Output: 2D classification results, saved in the output directory.
'''

def setupParserOptions():
    ap = argparse.ArgumentParser()
    ## General inputs
    ap.add_argument('-i', '--input',
                    help="Provide star file of the ctf corrected micrographs.")
    ap.add_argument('-o','--output', default='2DClass',
                    help="Name of the directory where the outputs of 2d classification are stored.")
    ap.add_argument('-p', '--program', default='relion_2DClass',
                    help='The program to use to do particle extraction. Currently only supports relion_class2d.')
    ## Program specific parameters
    ap.add_argument('-d', '--diameter',
                    help="Diameter of the particle to be used in 2D classification (in Angstrom).")
    ap.add_argument('-K', '--numclass',
                    help="Number of classes to be used in 2D classification. Default is 200 (the max allowed).")
    ap.add_argument('--tau2_fudge',
                    help="Regularisation parameter (values higher than 1 give more weight to the data).")
    ap.add_argument('--ctf', action='store_true',
                    help="Whether to do ctf correction. Default is FALSE.")
    ap.add_argument('--ctf_intact_first_peak', action='store_true',
                    help="Whether to ignore ctf until first peak. Default is FALSE.")
    ap.add_argument('--zero_mask', action='store_true',
                    help="Mask surrounding background in particles to zero. Default is FALSE.")
    ## Cluster submission needed
    ap.add_argument('--template', default='lsi_submit_template.sh', help="Name of the submission template.")
    ap.add_argument('--cluster', default='lsi', help='The computer cluster the job will run on.')
    ap.add_argument('--jobname', default='2DClassification', help='Jobname on the submission script.')
    # ap.add_argument('--user_email', help='User email address to send the notification to.')
    ap.add_argument('--walltime', default='48:00:00', help='Expected max run time of the job.')
    ap.add_argument('--nodes', default='2',help='Number of nodes used in the computer cluster.')

    args = vars(ap.parse_args())
    return args

def editparameters(s, diameter, k, tau2_fudge, ctf, ctf_intact_first_peak, zero_mask):
    if not ctf:
        assert not ctf_intact_first_peak
    new_s = s.replace('$$diameter', diameter).replace('$$K', k).replace('$$tau2_fudge', tau2_fudge)
    if ctf:
        new_s += '--ctf '
    if ctf_intact_first_peak:
        new_s += '--ctf_intact_first_peak '
    if zero_mask:
        new_s += '--zero_mask '
    return new_s

def check_good(class_dir):
    '''
    Currently only supports relion 2D classification.
    Check if 'run_it025_model.star' file exists.
    '''
    return os.path.isfile(os.path.join(class_dir, 'run_it025_model.star'))

def submit(**args):

    cluster = args['cluster']
    codedir = os.path.abspath(os.path.join(os.path.realpath(sys.argv[0]), os.pardir))
    wkdir = os.path.abspath(os.path.join(os.path.dirname(args['input']), os.pardir))
    cluster_config_file='cluster_config.json'
    job_config_file = '2DClass_config.json'

    ## mkdir to setup the job
    os.chdir(wkdir)
    try:
        os.mkdir(args['output'])
    except OSError:
        pass

    os.chdir(codedir)
    with open(cluster_config_file, 'r') as f:
        cluster_config = json.load(f)
    with open(job_config_file, 'r') as f:
        job_config = json.load(f)

    jobname = args['jobname']
    # user_email = args['user_email']
    walltime = args['walltime']
    program = args['program']
    nodes = args['nodes']
    # np = str(4*int(nodes))

    ctf = 1 if args['ctf'] else 0
    ctf_intact_first_peak = 1 if args['ctf_intact_first_peak'] else 0
    zero_mask = 1 if args['zero_mask'] else 0
    params = [
        ('diam-{:s}', args['diameter']),
        ('K-{:s}', args['numclass']),
        ('tau2-{:s}', args['tau2_fudge']),
        ('ctf-{:01d}', ctf),
        ('ign1p-{:01d}', ctf_intact_first_peak),
        ('zerom-{:01d}', zero_mask)]
    specs = '_'.join([t.format(v) for (t, v) in params])

    submit_name = 'submit_%s_%s.sh' %(args['program'], specs)
    input = '--i %s '%args['input']
    output_dir = os.path.join(args['output'], specs)
    output = '--o %s/run '%output_dir
    stdout = os.path.join('> %s'%output_dir, 'run_%s.out '%args['program'])
    stderr = os.path.join('2> %s'%output_dir, 'run_%s.err '%args['program'])
    module = 'module load relion/3.1beta-cluster/openmpi/4.0.2'
    conda_env = ''
    command = 'mpirun -np $NSLOTS `which relion_refine_mpi` '
    parameters = editparameters(job_config[program]['parameters'], \
                                args['diameter'], args['numclass'], args['tau2_fudge'],
                                args['ctf'], args['ctf_intact_first_peak'], args['zero_mask'])

    write_submit_lsi(codedir, wkdir, submit_name, \
                        jobname, walltime, nodes, \
                        job_config_file, program, \
                        input, output, stdout, stderr, \
                        module, conda_env, command, parameters, \
                        template_file=args['template'],\
                        cluster='lsi')

    os.chdir(wkdir)
    try:
        shutil.rmtree(output_dir)
        os.mkdir(output_dir)
    except OSError:
        os.mkdir(output_dir) # make "diamxxxkxxx" directory under the output directory

    cmd = 'qsub ' + submit_name
    job_id = subprocess.check_output(cmd, shell=True)
    job_id = job_id.decode("utf-8")
    job_id = str(int(job_id))
    with open('%s_%s_log.txt' %(args['program'], specs), 'a+') as f:
        f.write('Job submitted. Parameters is %s. Job ID is %s.\n' %(specs, job_id))
    query_cmd = cluster_config[cluster]['query_cmd']
    keyarg = cluster_config[cluster]['keyarg']
    # os.chdir(codedir) ## cd back to the directory of the code
    return job_id, query_cmd, keyarg


def check_complete(job_id, query_cmd, keyarg):
    ## Below: check every 2 seconds if the job has finished.
    state = check_state_lsi(query_cmd, job_id, keyarg)
    start_time = time.time()
    interval = 2
    while state!='C':
        time.sleep(interval)
        state = check_state_lsi(query_cmd, job_id, keyarg)

def check_output_good(**args):
    wkdir = os.path.abspath(os.path.join(os.path.dirname(args['input']), os.pardir))
    os.chdir(wkdir)

    ctf = 1 if args['ctf'] else 0
    ctf_intact_first_peak = 1 if args['ctf_intact_first_peak'] else 0
    zero_mask = 1 if args['zero_mask'] else 0
    params = [
        ('diam-{:s}', args['diameter']),
        ('K-{:s}', args['numclass']),
        ('tau2-{:s}', args['tau2_fudge']),
        ('ctf-{:01d}', ctf),
        ('ign1p-{:01d}', ctf_intact_first_peak),
        ('zerom-{:01d}', zero_mask)]
    specs = '_'.join([t.format(v) for (t, v) in params])
    output_dir = os.path.join(args['output'], specs)

    ## Below: check if the particle picking output is correct.
    with open('%s_%s_log.txt' %(args['program'], specs), 'a+') as f:
        f.write('Checking outputs....\n')
    isgood = check_good(output_dir)
    with open('%s_%s_log.txt' %(args['program'], specs), 'a+') as f:
        if isgood:
            f.write('2D classification for %s has finished.\n'%specs)
        else:
            f.write('Submission job %s is done but the output may not be right. Please check.\n'%specs)

if __name__ == '__main__':
    args = setupParserOptions()
    job_id, query_cmd, keyarg = submit(**args)
    check_complete(job_id, query_cmd, keyarg)
    check_output_good(**args)
