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
        self.votes = [
            {"validator": name, "confirmed": True, "reason": "Confirmado"}
            for name in ("V1", "V2")
        ]

    def api(self, endpoint, *, payload=None, paginate=False):
        if endpoint == self.endpoint and payload is None:
            return self.pr
        if endpoint != self.endpoint + "/comments":
            self.fail(f"Endpoint inesperado: {endpoint}")
        if payload is None:
            self.assertTrue(paginate)
            return [self.comments[:1], self.comments[1:]]
        comment = {**payload, "html_url": f"https://example.com/{len(self.comments) + 1}"}
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
