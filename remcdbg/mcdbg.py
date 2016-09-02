from __future__ import print_function
from remcdbg.utils import min_lexo
from remcdbg.utils import bits
from remcdbg.utils import kmer_to_bits
from remcdbg.utils import bits_to_kmer
import redis
import math
import sys
from collections import Counter
import json
import logging
logging.basicConfig()

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

KMER_SHARDING = {}

KMER_SHARDING[0] = {0: ''}
KMER_SHARDING[1] = {0: 'A', 1: 'T', 2: 'C', 3: 'G'}
KMER_SHARDING[2] = {0: 'AA', 1: 'AT', 2: 'AC', 3: 'AG', 4: 'TA', 5: 'TT', 6: 'TC',
                    7: 'TG', 8: 'CA', 9: 'CT', 10: 'CC', 11: 'CG', 12: 'GA', 13: 'GT', 14: 'GC', 15: 'GG'}
KMER_SHARDING[3] = {0: 'AAA', 1: 'AAT', 2: 'AAC', 3: 'AAG', 4: 'ATA', 5: 'ATT', 6: 'ATC', 7: 'ATG', 8: 'ACA', 9: 'ACT', 10: 'ACC', 11: 'ACG', 12: 'AGA', 13: 'AGT', 14: 'AGC', 15: 'AGG', 16: 'TAA', 17: 'TAT', 18: 'TAC', 19: 'TAG', 20: 'TTA', 21: 'TTT', 22: 'TTC', 23: 'TTG', 24: 'TCA', 25: 'TCT', 26: 'TCC', 27: 'TCG', 28: 'TGA', 29: 'TGT', 30: 'TGC', 31:
                    'TGG', 32: 'CAA', 33: 'CAT', 34: 'CAC', 35: 'CAG', 36: 'CTA', 37: 'CTT', 38: 'CTC', 39: 'CTG', 40: 'CCA', 41: 'CCT', 42: 'CCC', 43: 'CCG', 44: 'CGA', 45: 'CGT', 46: 'CGC', 47: 'CGG', 48: 'GAA', 49: 'GAT', 50: 'GAC', 51: 'GAG', 52: 'GTA', 53: 'GTT', 54: 'GTC', 55: 'GTG', 56: 'GCA', 57: 'GCT', 58: 'GCC', 59: 'GCG', 60: 'GGA', 61: 'GGT', 62: 'GGC', 63: 'GGG'}


def execute_pipeline(p):
    p.execute()


def logical_AND_reduce(list_of_bools):
    return [all(l) for l in zip(*list_of_bools)]


def logical_OR_reduce(list_of_bools):
    return [any(l) for l in zip(*list_of_bools)]


def byte_to_bitstring(byte):
    a = str("{0:b}".format(ord(byte)))
    if len(a) < 8:
        a = "".join(['0'*(8-len(a)), a])
    return a


class McDBG(object):

    def __init__(self, ports, kmer_size=31, compress_kmers=True):
        # colour
        self.ports = ports
        self.sharding_level = int(math.log(len(ports), 4))
        assert len(ports) in [1, 4, 64]
        self.connections = {}
        self._create_connections()
        self.num_colours = self.get_num_colours()
        self.kmer_size = kmer_size
        self.bitpadding = 2
        self.compress_kmers = compress_kmers

    def delete(self):
        for k, v in self.connections.items():
            for i, connection in v.items():
                connection.flushall()

    def shutdown(self):
        for v in self.connections.values():
            for connection in v.values():
                connection.shutdown()

    def _kmer_to_bytes(self, kmer):
        bitstring = kmer_to_bits(kmer)
        if not self.bitpadding == 0:
            bitstring = "".join([bitstring, '0'*self.bitpadding])
        # [self.sample_redis.setbit('tmp', int(i), int(j))
        #  for i, j in enumerate(bitstring)]
        # out = self.sample_redis.get('tmp')
        list_of_bytes = [bitstring[i:i+8] for i in range(0, len(bitstring), 8)]
        out = []
        for byte in list_of_bytes:
            out.append(bytes([int(byte, 2)]))
        _bytes = [int(byte, 2) for byte in list_of_bytes]
        out = bytes(_bytes)
        return out  # "".join(out)

    def _bytes_to_kmer(self, _bytes):
        a = "".join([byte_to_bitstring(byte) for byte in list(_bytes)])
        return bits_to_kmer(a, self.kmer_size)

    def _create_connections(self):
        # kmers stored in DB 2
        # colour arrays in DB 1
        # stats in DB 0
        self.connections['stats'] = {}
        self.connections['colours'] = {}
        self.connections['kmers'] = {}
        for i, port in enumerate(self.ports):
            self.connections['stats'][i] = redis.StrictRedis(
                host='localhost', port=port, db=0)
            # self.connections['colours'][i] = redis.StrictRedis(
            #     host='localhost', port=port, db=1)
            kmer_key = KMER_SHARDING[self.sharding_level][i]
            self.connections['kmers'][kmer_key] = redis.StrictRedis(
                host='localhost', port=port, db=2)

    def _create_kmer_pipeline(self, transaction=True):
        # kmers stored in DB 2
        # colour arrays in DB 1
        # stats in DB 0
        pipelines = {}
        for i, port in enumerate(self.ports):
            kmer_key = KMER_SHARDING[self.sharding_level][i]
            pipelines[kmer_key] = self.connections[
                'kmers'][kmer_key].pipeline(transaction=transaction)
        return pipelines

    def _execute_pipeline(self, pipelines):
        out = {}
        for kmer_key, p in pipelines.items():
            out[kmer_key] = p.execute()
        return out

    def set_kmer(self, kmer, colour, c=None):
        if c is None:
            c = self.connections['kmers'][
                kmer[:self.sharding_level]]
        if self.compress_kmers:
            # logger.debug('setting %s' % list(self._kmer_to_bytes(kmer)))
            # logger.debug('type is %s' % type(self._kmer_to_bytes(kmer)))
            c.setbit(self._kmer_to_bytes(kmer), colour, 1)
            # print(" SETBIT", self._kmer_to_bytes(
            #     kmer), colour, 1)
        else:
            c.setbit(kmer, colour, 1)
            # print(" SETBIT", kmer, colour, 1)

    # def _byte_encode(self, _bytes):
    #     byte_string = _bytes.__repr__()[2:-1]
    #     return self._bytestring_encode(byte_string)

    # def _bytestring_encode(self, byte_string):
    #     if '"' in byte_string:
    #         return '"%s"' % self._bytestring_replace(byte_string)
    #     elif "'" in byte_string:
    #         return '"%s"' % self._bytestring_replace(byte_string)
    #     elif " " in byte_string:
    #         return '"%s"' % self._bytestring_replace(byte_string)
    #     else:
    #         return byte_string

    # def _bytestring_replace(self, byte_string):
    #     a = "".join([s.replace('"', '\"').replace("'", "\'").replace(" ", "\ ")
    #                  for s in list(byte_string)])
    #     # byte_string.replace('"', '\"', len(byte_string)).replace("'", "\'",
    #     # len(byte_string)).replace(" ", "\ ", len(byte_string))
    #     return a.replace("\\\\'", "\\\\\\'")

    def set_kmers(self, kmers, colour, min_lexo=False):
        if not min_lexo:
            kmers = self._convert_query_kmers(kmers)
        # logger.debug('setting %s' % kmers)
        pipelines = self._create_kmer_pipeline(transaction=False)
        for kmer in kmers:
            self.set_kmer(kmer, colour, pipelines[kmer[:self.sharding_level]])
        self._execute_pipeline(pipelines)

    def _convert_query_kmers(self, kmers):
        return [min_lexo(k) for k in kmers]

    def _create_bitop_lists(self, kmers):
        bit_op_lists = dict((el, [])
                            for el in self.connections['kmers'].keys())
        for kmer in kmers:
            try:
                bit_op_lists[kmer[:self.sharding_level]].append(kmer)
            except KeyError:
                pass
        return bit_op_lists

    def bitops(self, kmers, op):
        bit_op_lists = self._create_bitop_lists(kmers)
        temporary_bitarrays = []
        for shard_key, kmers in bit_op_lists.items():
            if kmers:
                temporary_bitarrays.append(
                    self.single_bit_op(shard_key, op, kmers))
        return temporary_bitarrays

    def single_bit_op(self, shard_key, op, kmers):
        self.connections['kmers'][
            shard_key].bitop(op, 'tmp%s' % op, *kmers)
        return self._byte_arrays_to_bits(self.connections['kmers'][
            shard_key].get('tmp%s' % op))

    def query_kmers(self, kmers):
        kmers = self._convert_query_kmers(kmers)
        pipelines = self._create_kmer_pipeline()
        for kmer in kmers:
            c = pipelines[kmer[:self.sharding_level]]
            if self.compress_kmers:
                c.get(self._kmer_to_bytes(kmer))
            else:
                c.get(kmer)
        result = self._execute_pipeline(pipelines)
        out = [self._byte_arrays_to_bits(
            result[kmer[:self.sharding_level]].pop(0)) for kmer in kmers]
        return out

    def query_kmers_100_per(self, kmers, min_lexo=False):
        if not min_lexo:
            kmers = self._convert_query_kmers(kmers)
        temporary_bitarrays = self.bitops(kmers, "AND")
        return logical_AND_reduce(temporary_bitarrays)

    def get_non_0_kmer_colours(self, kmers):
        kmers = self._convert_query_kmers(kmers)
        return [i for i, j in enumerate(
                logical_OR_reduce(self.bitops(kmers, 'OR'))) if j == 1]

    def query_kmers_colours(self, kmers, colours=None):
        kmers = self._convert_query_kmers(kmers)

        if colours is None:
            colours = self.get_non_0_kmer_colours(kmers)
        pipelines = self._create_kmer_pipeline()
        num_colours = self.num_colours
        if colours:
            for kmer in kmers:
                for colour in colours:
                    pipelines[kmer[:self.sharding_level]].getbit(kmer, colour)
        result = self._execute_pipeline(pipelines)
        outs = [colours]
        if colours:
            for kmer in kmers:
                out = []
                for _ in colours:
                    out.append(result[kmer[:self.sharding_level]].pop(0))
                outs.append(tuple(out))
        return outs

    def _byte_arrays_to_bits(self, _bytes):
        num_colours = self.num_colours
        tmp_v = [0]*(num_colours)
        if _bytes is not None:
            tmp_v = bits(_bytes)
        if len(tmp_v) < num_colours:
            tmp_v.extend([0]*(num_colours-len(tmp_v)))
        elif len(tmp_v) > num_colours:
            tmp_v = tmp_v[:num_colours]
        return tuple(tmp_v)

    def kmers(self, N=-1, k='*'):
        i = 0
        for connections in self.connections['kmers'].values():
            for kmer in connections.scan_iter(k):
                i += 1
                if (i > N and N > 0):
                    break
                yield kmer

    def add_sample(self, sample_name):
        existing_index = self.get_sample_colour(sample_name)
        if existing_index is not None:
            raise ValueError("%s already exists in the db" % sample_name)
        else:
            num_colours = self.sample_redis.get('num_colours')
            if num_colours is None:
                num_colours = 0
            else:
                num_colours = int(num_colours)
            pipe = self.sample_redis.pipeline()
            pipe.set('s%s' % sample_name, num_colours).incr('num_colours')
            pipe.execute()
            return num_colours

    def get_sample_colour(self, sample_name):
        return self.sample_redis.get('s%s' % sample_name)

    def colours_to_sample_dict(self):
        o = {}
        for s in self.sample_redis.keys('s*'):
            o[int(self.sample_redis.get(s))] = s[1:]
        return o

    @property
    def sample_redis(self):
        return self.connections['stats'][0]

    def get_num_colours(self):
        try:
            return int(self.sample_redis.get('num_colours'))
        except TypeError:
            return 0

    def count_kmers(self):
        return sum([r.dbsize() for r in self.connections['kmers'].values()])

    def calculate_memory(self):
        memory = sum([r.info().get('used_memory')
                      for r in self.connections['kmers'].values()])
        self.connections['stats'][1].set([self.count_kmers()], memory)
        return memory

    def bitcount_all(self):
        count = Counter()
        pipelines = None
        for i, kmer in enumerate(self.kmers()):
            if i % 100000*len(self.ports) == 0:
                if pipelines:
                    result = self._execute_pipeline(pipelines)
                    [count.update(l) for l in result.values()]
                    print(json.dumps(dict(count)))
                pipelines = self._create_kmer_pipeline(transaction=False)
                sys.stderr.write(
                    '%i of %i %f%%\n' % (i, self.count_kmers(), float(i)/self.count_kmers()))
            try:
                pipelines[kmer[:self.sharding_level]].bitcount(kmer)
            except KeyError:
                pass

        return dict(count)


# >>> with r.pipeline() as pipe:
# ...     while 1:
# ...         try:
# ...             # put a WATCH on the key that holds our sequence value
# ...             pipe.watch('OUR-SEQUENCE-KEY')
# ...             # after WATCHing, the pipeline is put into immediate execution
# ...             # mode until we tell it to start buffering commands again.
# ...             # this allows us to get the current value of our sequence
# ...             current_value = pipe.get('OUR-SEQUENCE-KEY')
# ...             next_value = int(current_value) + 1
# ...             # now we can put the pipeline back into buffered mode with MULTI
# ...             pipe.multi()
# ...             pipe.set('OUR-SEQUENCE-KEY', next_value)
# ...             # and finally, execute the pipeline (the set command)
# ...             pipe.execute()
# ...             # if a WatchError wasn't raised during execution, everything
# ...             # we just did happened atomically.
# ...             break
# ...        except WatchError:
# ...             # another client must have changed 'OUR-SEQUENCE-KEY' between
# ...             # the time we started WATCHing it and the pipeline's execution.
# ...             # our best bet is to just retry.
# ...             continue
