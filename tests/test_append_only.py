import hashlib,json,tempfile,unittest
from pathlib import Path
from lottery.append_only import AppendOnlyError,reconcile_append_only

def row(i,d,front=None):
 return {"draw_id":i,"draw_date":d,"front_numbers":front or [1,2,3,4,5],"back_numbers":[1,2],
 "source_id":"sha256:fixture","front_draw_order":None,"back_draw_order":None,
 "source_unsort_drawresult":None,"source_equipment_count":None}
def write_rows(p,rows): p.write_text("".join(json.dumps(r,sort_keys=True)+"\n" for r in rows),encoding="utf-8")
def manifest(c,m):
 m.write_text(json.dumps({"output_sha256":hashlib.sha256(c.read_bytes()).hexdigest(),
 "trust_status":"manifest_complete_not_officially_authenticated","provenance_complete":True,
 "snapshot_count":1,"validation":{"records":len(c.read_text().splitlines())}}),encoding="utf-8")

class AppendOnlyTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory(); self.root=Path(self.t.name)
  self.cur=self.root/"current.jsonl"; self.can=self.root/"candidate.jsonl"; self.man=self.root/"candidate.manifest.json"
  self.out=self.root/"published.jsonl"; self.receipt=self.root/"receipt.json"
  self.old=[row("26130","2026-11-14"),row("26131","2026-11-16")]; write_rows(self.cur,self.old)
 def tearDown(self): self.t.cleanup()
 def prep(self,rows): write_rows(self.can,rows); manifest(self.can,self.man)
 def run_gate(self): return reconcile_append_only(self.cur,self.can,self.man,self.out,self.receipt)
 def test_append_and_hash_receipt(self):
  self.prep(self.old+[row("26132","2026-11-18")]); r=self.run_gate()
  self.assertEqual(r["status"],"appended"); self.assertEqual(r["appended_draw_ids"],["26132"])
  self.assertEqual(hashlib.sha256(self.out.read_bytes()).hexdigest(),r["output_sha256"])
 def test_no_new_draw_is_idempotent_and_writes_no_output(self):
  self.prep(self.old); r=self.run_gate(); self.assertEqual(r["status"],"no_new_draws"); self.assertFalse(self.out.exists())
 def test_missing_history_rejected(self):
  self.prep([self.old[-1]])
  with self.assertRaisesRegex(AppendOnlyError,"not a full snapshot"): self.run_gate()
 def test_correction_rejected_without_overwrite(self):
  self.prep([self.old[0],row("26131","2026-11-16",[1,2,3,4,6])])
  with self.assertRaisesRegex(AppendOnlyError,"historical correction"): self.run_gate()
  self.assertFalse(self.out.exists())
 def test_chronology_regression_rejected(self):
  self.prep([self.old[0],row("26129","2026-11-15"),self.old[1]])
  with self.assertRaisesRegex(AppendOnlyError,"not strictly after"): self.run_gate()
 def test_candidate_hash_mismatch_rejected(self):
  self.prep(self.old); self.can.write_text(self.can.read_text().rstrip("\\n")+" ")
  with self.assertRaisesRegex(AppendOnlyError,"output_sha256"): self.run_gate()
 def test_incomplete_source_manifest_rejected(self):
  self.prep(self.old+[row("26132","2026-11-18")]); x=json.loads(self.man.read_text()); x["trust_status"]="candidate_unverified"; self.man.write_text(json.dumps(x))
  with self.assertRaisesRegex(AppendOnlyError,"complete official-source"): self.run_gate()
 def test_source_reference_change_is_not_a_result_correction(self):
  revised=[dict(r,source_id="sha256:new") for r in self.old]; self.prep(revised+[row("26132","2026-11-18")])
  self.assertEqual(self.run_gate()["status"],"appended")
  published=[json.loads(x) for x in self.out.read_text().splitlines()]
  self.assertEqual(published[0]["source_id"],"sha256:fixture")

 def test_output_must_not_overwrite_current_dataset(self):
  self.prep(self.old+[row("26132","2026-11-18")])
  with self.assertRaisesRegex(AppendOnlyError,"paths must be distinct"):
   reconcile_append_only(self.cur,self.can,self.man,self.cur,self.receipt)
 def test_receipt_must_not_overwrite_candidate_manifest(self):
  self.prep(self.old)
  with self.assertRaisesRegex(AppendOnlyError,"paths must be distinct"):
   reconcile_append_only(self.cur,self.can,self.man,self.out,self.man)
\nif __name__=="__main__": unittest.main()
