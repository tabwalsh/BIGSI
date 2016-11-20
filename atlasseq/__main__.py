#! /usr/bin/env python
from __future__ import print_function
import sys
import os
import argparse
import redis
import json
sys.path.append(
    os.path.realpath(
        os.path.join(
            os.path.dirname(__file__),
            "..")))
from atlasseq.version import __version__
import logging
logging.basicConfig(level=logging.DEBUG)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

import hug
from atlasseq.graph import ProbabilisticMultiColourDeBruijnGraph as Graph

BFSIZE = int(os.environ.get("BFSIZE", 20000000))
NUM_HASHES = int(os.environ.get("NUM_HASHES", 3))
BULK_CMD_OUTDIR = os.environ.get("BULK_CMD_OUTDIR")
CONN_CONFIG = []
redis_envs = [env for env in os.environ if "REDIS" in env]
if len(redis_envs) == 0:
    CONN_CONFIG = [('localhost', 7000, 2)]
else:
    for i in range(int(len(redis_envs)/2)):
        hostname = os.environ.get("REDIS_IP_%s" % str(i + 1))
        port = int(os.environ.get("REDIS_PORT_%s" % str(i + 1)))
        CONN_CONFIG.append((hostname, port, 2))
GRAPH = Graph(storage={'redis-cluster': {"conn": CONN_CONFIG, "bulk_commands_directory": BULK_CMD_OUTDIR}},
              bloom_filter_size=BFSIZE, num_hashes=NUM_HASHES)
from atlasseq.cmds.insert import insert
from atlasseq.cmds.search import search
from atlasseq.cmds.stats import stats
from atlasseq.cmds.samples import samples
from atlasseq.cmds.dump import dump
from atlasseq.cmds.load import load
from atlasseq.cmds.delete import delete
#from atlasseq.cmds.bitcount import bitcount
#from atlasseq.cmds.jaccard_index import jaccard_index


API = hug.API('atlas')


@hug.object(name='atlas', version='0.0.1', api=API)
@hug.object.urls('/', requires=())
class AtlasSeq(object):

    @hug.object.cli
    @hug.object.post('/insert', output_format=hug.output_format.json)
    def insert(self, kmers=None, kmer_file=None, sample=None, force: hug.types.smart_boolean=False,
               intersect_kmers_file=None, count_only: hug.types.smart_boolean = False):
        """Inserts kmers from a list of kmers into the graph

        e.g. atlasseq insert ERR1010211.txt

        """
        if not kmers and not kmer_file:
            return "--kmers or --kmer_file must be provided"
        return insert(kmers=kmers,
                      kmer_file=kmer_file, graph=GRAPH, force=force, sample_name=sample,
                      intersect_kmers_file=intersect_kmers_file, count_only=count_only)

    @hug.object.cli
    @hug.object.get('/search', examples="seq=ACACAAACCATGGCCGGACGCAGCTTTCTGA", output_format=hug.output_format.json)
    def search(self, seq: hug.types.text=None, fasta: hug.types.text=None, threshold: hug.types.float_number=1.0):
        """Returns samples that contain the searched sequence. 
        Use -f to search for sequence from fasta"""
        if not seq and not fasta:
            return "-s or -f must be provided"
        return search(seq=seq,
                      fasta_file=fasta, threshold=threshold, graph=GRAPH)

    @hug.object.cli
    @hug.object.delete('/', output_format=hug.output_format.json)
    def delete(self):
        return delete(graph=GRAPH)

    @hug.object.cli
    @hug.object.get('/graph', output_format=hug.output_format.json)
    def stats(self):
        return stats(graph=GRAPH)

    @hug.object.cli
    @hug.object.get('/samples', output_format=hug.output_format.json)
    def samples(self, name=None):
        return samples(name, graph=GRAPH)

    @hug.object.cli
    @hug.object.post('/dump', output_format=hug.output_format.json)
    def dump(self, filepath):
        r = dump(graph=GRAPH, file=filepath)
        return r

    @hug.object.cli
    @hug.object.post('/load', output_format=hug.output_format.json)
    def load(self, filepath):
        r = load(graph=GRAPH, file=filepath)
        return r
    # @hug.object.cli
    # @hug.object.get('/bitcount')
    # def bitcount(self):
    #     return bitcount(graph=GRAPH)

    # @hug.object.cli
    # @hug.object.get('/js')
    # def distance(self, s1=None, s2=None):
    # return json.dumps(jaccard_index(s1, s2, graph=GRAPH),
    # indent=1)


def main():
    API.cli()

if __name__ == "__main__":
    main()
