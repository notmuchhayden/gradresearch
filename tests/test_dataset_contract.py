from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from dataset_contract import cross_view_gt_depth,frame_split,triangulate_faces,validate_poses


class DatasetContractTests(unittest.TestCase):
    def test_triangle_and_quad_conversion_preserves_source_winding(self):
        triangles,counts=triangulate_faces(np.array([[0,1,2,3],[3,2,4,5]]),6)
        np.testing.assert_array_equal(triangles,[[0,1,2],[0,2,3],[3,2,4],[3,4,5]])
        self.assertEqual(counts,{"4":2})
        mixed=np.empty(2,dtype=object);mixed[0]=np.array([0,1,2]);mixed[1]=np.array([0,2,3,4])
        triangles,counts=triangulate_faces(mixed,5)
        np.testing.assert_array_equal(triangles,[[0,1,2],[0,2,3],[0,3,4]])
        self.assertEqual(counts,{"3":1,"4":1})

    def test_invalid_polygon_indices_and_arity_are_rejected(self):
        for faces in (np.array([[0,1]]),np.array([[0,1,-1]]),np.array([[0,1,9]]),np.empty((0,3),dtype=int)):
            with self.assertRaises(ValueError):triangulate_faces(faces,5)

    def qa(self):
        return {"edge_mask":{"depth_valid_range_m":[.1,10],"depth_edge_abs_m":.05,
                "depth_edge_relative":.02,"depth_edge_dilation_pixels":2},
                "cross_view_sample_grid_stride":4,"cross_view_min_common_samples":100,
                "cross_view_median_abs_depth_residual_max_m":.03,
                "cross_view_consistency_abs_tolerance_m":.05,
                "cross_view_consistency_relative_tolerance":.02,"cross_view_min_consistent_fraction":.9}

    def test_mapping_calibration_and_heldout_do_not_overlap(self):
        s=frame_split(1000,200)
        self.assertEqual(s["model_input_rgb"].sum(),500)
        self.assertEqual(s["calibration_pose"].sum(),100)
        self.assertEqual(s["primary_eval_view"].sum(),400)
        self.assertFalse((s["model_input_rgb"]&s["primary_eval_view"]).any())
        self.assertFalse((s["calibration_pose"]&s["primary_candidate_anchor_eligible"]).any())
        self.assertEqual(s["original_frame_id"][s["primary_eval_view"]][0],201)
        self.assertEqual(sum(s[k].sum() for k in ["model_input_rgb","primary_eval_view","unused_prefix_odd"]),1000)

    def test_empty_or_overlapping_prefix_is_rejected(self):
        for prefix in (0,1,1000,2000):
            with self.assertRaises(ValueError):frame_split(1000,prefix)

    def test_metric_gt_pose_validation_rejects_scale_and_bad_rows(self):
        good=np.repeat(np.eye(4)[None],5,axis=0)
        self.assertEqual(validate_poses(good,5)["pose_rows"],5)
        for mutation in ("scale","bottom","nan","short"):
            bad=good.copy()
            if mutation=="scale":bad[2,:3,:3]*=2
            elif mutation=="bottom":bad[0,3,0]=1
            elif mutation=="nan":bad[1,0,0]=np.nan
            else:bad=bad[:2]
            with self.assertRaises(ValueError):validate_poses(bad,5)

    def test_known_frontoparallel_plane_across_translated_cameras(self):
        depth=np.full((64,64),2.,np.float32)
        K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1]])
        source=np.eye(4);target=np.eye(4);target[0,3]=.08
        result=cross_view_gt_depth(depth,depth,source,target,K,self.qa())
        self.assertEqual(result["status"],"PASS")
        self.assertAlmostEqual(result["median_abs_z_residual_m"],0)

    def test_wrong_pose_or_time_association_fails_depth_consistency(self):
        depth=np.full((64,64),2.,np.float32)
        K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1]])
        wrong=np.eye(4);wrong[2,3]=.3
        result=cross_view_gt_depth(depth,depth,np.eye(4),wrong,K,self.qa())
        self.assertEqual(result["status"],"FAIL")
        self.assertAlmostEqual(result["median_abs_z_residual_m"],.3)

    def test_invalid_or_occluded_depth_does_not_pass_without_support(self):
        depth=np.full((64,64),2.,np.float32)
        target=np.zeros_like(depth)
        K=np.array([[50.,0,31.5],[0,50.,31.5],[0,0,1]])
        result=cross_view_gt_depth(depth,target,np.eye(4),np.eye(4),K,self.qa())
        self.assertEqual(result["status"],"FAIL")
        self.assertEqual(result["target_common_samples"],0)


if __name__=="__main__":unittest.main()
