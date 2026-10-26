import sys
from pathlib import Path
import numpy as np
import cv2
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from a0b_geometry import rasterize, resize_contract, source_rays, sampson_pixels


def test_sparse_z_buffer_keeps_holes_and_near_surface():
    uv=np.array([[1.,1.],[1.1,1.],[3.,3.],[np.nan,2.],[-2.,0.]])
    d,v,e,n=rasterize(uv,np.array([10.,10.1,20.,5.,5.]),(5,5))
    assert d[1,1]==10 and v[1,1] and n[1,1]==2
    assert np.count_nonzero(v)==2 and d[0,0]==0 and not v[0,0]


def test_discontinuous_cell_is_not_a_reference():
    d,v,e,n=rasterize(np.array([[1.,1.],[1.,1.],[4.,4.]]),np.array([10.,30.,15.]),(6,6))
    assert e[1,1] and not v[1,1] and v[4,4]


def test_raw_source_pixel_undistortion_roundtrip():
    K=np.array([[1451.,0,1177.],[0,1451.,1043.],[0,0,1.]])
    m=dict(K=K,distortion=np.array([-.05,.1,.001,0.,-.06]))
    pix=np.array([[220.,190.],[100.,90.],[400.,300.]])
    ray=source_rays(pix,m)
    uv=cv2.projectPoints(ray,np.zeros(3),np.zeros(3),K,m['distortion'])[0].reshape(-1,2)
    A,hw,_,_=resize_contract();assert hw==(416,512)
    np.testing.assert_allclose(uv@A[:2,:2].T+A[:2,2],pix,atol=1e-5)


def test_c2w_epipolar_convention():
    a=np.eye(4);b=np.eye(4);b[0,3]=1.;K=np.diag([100.,100.,1.])
    xyz=np.array([[1.,2.,10.],[2.,1.,8.]])
    def project(x):return (x@K.T)[:,:2]/x[:,2:]
    first=project(xyz);second=project(xyz-b[:3,3])
    np.testing.assert_allclose(sampson_pixels(first,second,a,b,K),0,atol=1e-12)


class SparseGeometryTests(unittest.TestCase):
    test_sparse_z_buffer_keeps_holes_and_near_surface = staticmethod(test_sparse_z_buffer_keeps_holes_and_near_surface)
    test_discontinuous_cell_is_not_a_reference = staticmethod(test_discontinuous_cell_is_not_a_reference)
    test_raw_source_pixel_undistortion_roundtrip = staticmethod(test_raw_source_pixel_undistortion_roundtrip)
    test_c2w_epipolar_convention = staticmethod(test_c2w_epipolar_convention)


if __name__ == '__main__':
    unittest.main()
