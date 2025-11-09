# Release Process

This document describes the steps to create a new release and publish the `life-model` package to PyPI.

## Overview

The release process uses GitHub Actions workflows that are triggered by Git tags. The workflows automatically build distribution files and publish them, so you don't need to build packages locally.

## Prerequisites

- All changes are merged to the `main` branch
- All tests are passing
- Version number is decided (e.g., `1.2.3`)

## Release Steps

### 1. Create and Push a Git Tag

Create a Git tag with the version number. This tag triggers the workflows and determines the package version:

```bash
# Ensure you're on the main branch and up to date
git checkout main
git pull

# Create a tag with the version number (must start with 'v')
git tag v1.2.3

# Push the tag to GitHub
git push origin v1.2.3
```

**Important:** The tag name must follow the format `vX.X.X` (e.g., `v1.2.3`) or the workflows will fail validation.

### 2. Test the Release on TestPyPI (Recommended)

Before publishing to the production PyPI, test the release on TestPyPI:

1. Go to the [Actions tab](https://github.com/sw23/life-model/actions) on GitHub
2. Select the **"Publish Python distribution to TestPyPI"** workflow
3. Click the **"Run workflow"** dropdown
4. Select the tag you just created (e.g., `v1.2.3`)
5. Click **"Run workflow"**

The workflow will validate the tag, build the distribution files (wheel and source tarball), and publish to [TestPyPI](https://test.pypi.org/p/life-model).

### 3. Verify the Test Release

Install and test the package from TestPyPI to ensure it works correctly:

```bash
pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ life-model==1.2.3
```

Run your tests or manually verify the package functionality.

### 4. Publish to Production PyPI

Once you've verified the test release works correctly:

1. Go to the [Actions tab](https://github.com/sw23/life-model/actions) on GitHub
2. Select the **"Publish Python distribution to PyPI"** workflow
3. Click the **"Run workflow"** dropdown
4. Select the same tag (e.g., `v1.2.3`)
5. Click **"Run workflow"**

The workflow will:
- Validate the tag format
- Build the distribution files
- Publish to [PyPI](https://pypi.org/p/life-model)
- Create a GitHub Release with auto-generated release notes
- Sign the distribution files with Sigstore
- Upload the distribution files and signatures to the GitHub Release

The package will be available on PyPI at `https://pypi.org/project/life-model/`
The GitHub Release will be available at `https://github.com/sw23/life-model/releases/`
