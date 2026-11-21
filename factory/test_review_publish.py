import subprocess
import unittest

from review_publish import publish_review


class ReviewPublicationTest(unittest.TestCase):
    def setUp(self):
        self.repo = "owner/repo"
        self.endpoint = f"repos/{self.repo}/pulls/8"
        self.base = "a" * 40
        self.head = "b" * 40
        self.pr = {"state": "open", "base": {"sha": self.base}, "head": {"sha": self.head}}
        self.comments = []
        self.reviews = []
        self.fail_pr_read_after_comment = False
        self.fail_reviews_read = False
        self.files = [{"filename": "README.md", "patch": "@@ -1,2 +1,3 @@\n a\n-b\n+B\n+c"}]
        self.votes = [
            {"validator": name, "confirmed": True, "reason": "Confirmado"}
            for name in ("V1", "V2")
        ]

    def api(self, endpoint, *, payload=None, paginate=False, method="POST"):
        if self.fail_pr_read_after_comment and self.comments and endpoint == self.endpoint and payload is None:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 503")
        if self.fail_reviews_read and endpoint == self.endpoint + "/reviews" and payload is None:
            raise subprocess.CalledProcessError(1, "gh", stderr="HTTP 503")
        if endpoint == self.endpoint and payload is None:
            return self.pr
        if endpoint == self.endpoint + "/files":
            return [self.files]
        if endpoint == self.endpoint + "/reviews":
            if payload is None:
                return [self.reviews]
            review = {**payload, "id": 1, "html_url": "https://example.com/review"}
            self.reviews.append(review)
            return review
        if endpoint == self.endpoint + "/reviews/1" and method == "PUT":
            self.reviews[0].update(payload)
            return self.reviews[0]
        if method == "PATCH":
            comment = self.comments[int(endpoint.rsplit("/", 1)[1]) - 1]
            comment.update(payload)
            return comment
        if endpoint != self.endpoint + "/comments":
            self.fail(f"Endpoint inesperado: {endpoint}")
        if payload is None:
            self.assertTrue(paginate)
            return [self.comments[:1], self.comments[1:]]
        comment = {**payload, "id": len(self.comments) + 1, "html_url": f"https://example.com/{len(self.comments) + 1}"}
        self.comments.append(comment)
        return comment

    def finding(self, **changes):
        return {
            "file": "README.md", "line": 3, "scenario": "Link do manual",
            "evidence": "O destino está ausente.", "impact": "O link falha.",
            "label": "nitpick", "revisor": "R1", "votes": self.votes, **changes,
        }

    def publish(self, *findings):
        return publish_review(self.api, self.repo, 8, {
            "repo": self.repo, "base_sha": self.base, "head_sha": self.head,
            "validators": ["V1", "V2"], "findings": list(findings),
        })

    def test_only_unanimous_finding_is_published_with_label_and_position(self):
        result = self.publish(self.finding(), self.finding(line=4, votes=self.votes[:1]))
        self.assertEqual(len(result["publicados"]), 1)
        self.assertEqual(len(result["internos"]), 1)
        comment, = self.comments
        self.assertEqual((comment["path"], comment["line"], comment["side"]), ("README.md", 3, "RIGHT"))
        self.assertEqual(comment["commit_id"], self.head)
        self.assertTrue(comment["body"].startswith("**Nitpick:**"))

    def test_reexecution_does_not_duplicate_comment_with_rephrased_text(self):
        self.comments.append({"body": "Comentário anterior"})
        self.publish(self.finding())
        result = self.publish(self.finding(scenario="Link para o manual"))
        self.assertEqual(len(self.comments), 2)
        self.assertEqual(len(result["existentes"]), 1)

    def test_changed_base_or_head_blocks_publication(self):
        for ref in ("base", "head"):
            with self.subTest(ref=ref):
                saved_sha = self.pr[ref]["sha"]
                self.pr[ref]["sha"] = "c" * 40
                result = self.publish(self.finding())
                self.assertEqual(result["estado"], "desatualizado")
                self.assertEqual(self.comments, [])
                self.pr[ref]["sha"] = saved_sha

    def test_new_finding_updates_existing_comment_on_same_line(self):
        first = self.finding()
        second = self.finding(scenario="Destino alternativo", evidence="O destino exige login.",
                              impact="O leitor sem conta não tem acesso.")
        self.publish(first)
        self.publish(first, second)
        self.publish(second)
        comment, = self.comments
        self.assertEqual(comment["body"].count("Link do manual"), 1)
        self.assertEqual(comment["body"].count("Destino alternativo"), 1)

    def test_off_diff_findings_are_grouped_in_review_summary_without_duplicates(self):
        inline = self.finding()
        outside = self.finding(file="factory/intake.py", line=11, label="já existente")
        outside_hunk = self.finding(line=51, label="importante")
        self.publish(inline, outside)
        result = self.publish(inline, outside, outside_hunk)
        self.assertEqual(len(result["publicados"]), 1)
        self.assertEqual(len(result["existentes"]), 2)
        self.assertEqual(len(self.comments), 1)
        review, = self.reviews
        self.assertEqual(review["commit_id"], self.head)
        self.assertEqual(review["event"], "COMMENT")
        self.assertEqual(review["body"].count("**Já existente:**"), 1)
        self.assertIn("**Importante:**", review["body"])
        self.assertIn(f"/blob/{self.head}/factory/intake.py#L11", review["body"])
        self.assertIn(f"/blob/{self.head}/README.md#L51", review["body"])

    def test_removed_line_is_not_commentable_on_new_side(self):
        self.files = [{"filename": "README.md", "patch": "@@ -1,3 +1,2 @@\n a\n-b\n-c\n+B"}]
        result = self.publish(self.finding(line=2), self.finding(line=3, label="importante"))
        self.assertEqual([(c["path"], c["line"]) for c in self.comments], [("README.md", 2)])
        review, = self.reviews
        self.assertIn(f"/blob/{self.head}/README.md#L3", review["body"])
        self.assertEqual(len(result["publicados"]), 2)

    def test_failure_after_published_comment_returns_link_and_pending(self):
        self.fail_pr_read_after_comment = True
        result = self.publish(
            self.finding(line=2),
            self.finding(line=3, scenario="Outro link", evidence="Outra evidência.", impact="Outro impacto."),
        )
        self.assertEqual(result["estado"], "pendente")
        self.assertEqual(result["publicados"], [{"file": "README.md", "line": 2, "url": "https://example.com/1"}])
        self.assertEqual(len(self.comments), 1)
        self.assertIn("HTTP 503", result["pendentes"][0]["motivo"])

    def test_summary_read_failure_keeps_inline_and_marks_outside_pending(self):
        self.fail_reviews_read = True
        result = self.publish(self.finding(line=3), self.finding(line=51, label="importante"))
        self.assertEqual(result["estado"], "pendente")
        self.assertEqual(len(result["publicados"]), 1)
        self.assertEqual(result["pendentes"], [{"file": "README.md", "line": 51, "motivo": "HTTP 503"}])
