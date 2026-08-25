import unittest


class PackageImportTest(unittest.TestCase):
    def test_package_imports(self) -> None:
        import supplychain

        self.assertIsNotNone(supplychain)


if __name__ == "__main__":
    unittest.main()

