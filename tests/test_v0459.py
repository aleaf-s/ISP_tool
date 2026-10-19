"""Independent official-layout checks, not just pack/unpack self-consistency."""
from pathlib import Path
import tempfile
from unittest import TestCase
import numpy as np
from isp_tool.grading.hisi_clut import (addresses,pack_deltas,unpack_words,
    read_words,load_hisi,export_hisi)


def reference_address(r,g,b):
    # Closed-form indexing independent of the production counter loop.
    rp,bp,gp=r%2,b%2,g%2
    group=rp+2*bp+4*gp
    rank=(g//2)*(9-bp)*(9-rp)+(b//2)*(9-rp)+r//2
    return (0 if gp==0 else 2916)+4*rank+group%4


class OfficialCLUTFormatTests(TestCase):
    def test_all_node_addresses_and_bank_sizes(self):
        coords,positions=addresses()
        expected=[reference_address(int(r),int(g),int(b)) for r,g,b in coords]
        np.testing.assert_array_equal(positions,expected)
        self.assertEqual(len(set(expected)),4913)
        self.assertEqual(5508-len(expected),595)
        groups=(coords[:,0]%2)+2*(coords[:,2]%2)+4*(coords[:,1]%2)
        self.assertEqual(np.bincount(groups).tolist(),[729,648,648,576,648,576,576,512])
        self.assertFalse(coords.flags.writeable);self.assertFalse(positions.flags.writeable)

    def test_full_encode_against_independent_reference(self):
        delta=np.random.default_rng(91).integers(-511,512,(17,17,17,3),dtype=np.int16)
        expected=np.zeros(5508,dtype=np.uint32)
        for r in range(17):
            for g in range(17):
                for b in range(17):
                    dr,dg,db=map(int,delta[r,g,b])
                    expected[reference_address(r,g,b)]=(dr%1024)+1024*(dg%1024)+1048576*(db%1024)
        np.testing.assert_array_equal(pack_deltas(delta),expected)
        np.testing.assert_array_equal(unpack_words(expected),delta)

    def test_known_word_and_channel_impulses(self):
        words=np.zeros(5508,dtype=np.int64);words[5324]=249543659
        self.assertEqual(reference_address(16,15,6),5324)
        delta=unpack_words(words)
        self.assertEqual(delta[16,15,6].tolist(),[-21,-18,237])
        np.testing.assert_array_equal(pack_deltas(delta),words)
        for channel,expected in enumerate((1023,1047552,1072693248)):
            delta=np.zeros((17,17,17,3),np.int16);delta[0,0,0,channel]=-1
            self.assertEqual(int(pack_deltas(delta)[0]),expected)

    def test_signed_limits_and_integer_minimum_never_wrap(self):
        for dtype in (np.int16,np.int32,np.int64):
            for invalid in (-512,512,np.iinfo(dtype).min):
                with self.subTest(dtype=dtype,value=invalid):
                    delta=np.zeros((17,17,17,3),dtype=dtype);delta[0,0,0,0]=invalid
                    with self.assertRaises(ValueError):pack_deltas(delta)
        delta=np.zeros((17,17,17,3),np.int16);delta[0,0,0]=(-511,0,511)
        self.assertEqual(unpack_words(pack_deltas(delta))[0,0,0].tolist(),[-511,0,511])
        for invalid in (.5,float('nan'),float('inf')):
            delta=np.zeros((17,17,17,3));delta[0,0,0,0]=invalid
            with self.assertRaises(ValueError):pack_deltas(delta)

    def test_every_padding_slot_and_reserved_bits_rejected(self):
        used={reference_address(r,g,b) for r in range(17) for g in range(17) for b in range(17)}
        for index in set(range(5508))-used:
            words=np.zeros(5508,dtype=np.int64);words[index]=1
            with self.assertRaises(ValueError):unpack_words(words)
        for value in (1<<30,1<<31,-1,512,512<<10,512<<20):
            words=np.zeros(5508,dtype=np.int64);words[0]=value
            with self.assertRaises(ValueError):unpack_words(words)

    def test_supplied_files_keep_every_word_and_txt_layout(self):
        samples=[Path('D:/Rroject_Remo_AWB/01_Param/02_Hisi/CLUT/lantian_caodi.txt')]
        samples.extend(Path('C:/Users/remo/Downloads')/n for n in ('111.txt','222CLUT.txt','10CLUT.txt','0CLUT.txt','74CLUT.txt'))
        existing=[p for p in samples if p.exists()]
        if not existing:self.skipTest('Local user samples unavailable')
        with tempfile.TemporaryDirectory() as folder:
            for path in existing:
                with self.subTest(file=path.name):
                    original=read_words(path);out=Path(folder)/'out.txt'
                    export_hisi(out,load_hisi(path))
                    np.testing.assert_array_equal(read_words(out),original)
                    lines=out.read_text().splitlines();self.assertEqual(len(lines),612)
                    self.assertTrue(all(len(line.rstrip(',').split(','))==9 for line in lines))
                    if path.name=='lantian_caodi.txt':self.assertEqual(int(original[5324]),249543659)
