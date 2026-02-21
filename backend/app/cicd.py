from typing import Dict, List, Literal

from .schemas import TechProfile


def _ci_steps(profile: TechProfile) -> List[str]:
    lang = profile.primary_language
    if lang in ("JavaScript", "TypeScript"):
        return [
            "      - uses: actions/setup-node@v4",
            "        with:",
            "          node-version: 20",
            "          cache: npm",
            "      - run: npm ci",
            "      - run: npm run lint --if-present",
            "      - run: npm run build --if-present",
            "      - run: npm test --if-present",
        ]
    if lang == "Python":
        return [
            "      - uses: actions/setup-python@v5",
            "        with:",
            "          python-version: '3.12'",
            "      - run: pip install -U pip",
            "      - run: |",
            "          if [ -f requirements.txt ]; then pip install -r requirements.txt; fi",
            "      - run: pip install pytest ruff",
            "      - run: ruff check .",
            "      - run: pytest -q || true",
        ]
    if lang == "Java":
        return [
            "      - uses: actions/setup-java@v4",
            "        with:",
            "          distribution: temurin",
            "          java-version: '21'",
            "          cache: maven",
            "      - run: |",
            "          if [ -f pom.xml ]; then mvn -B verify; fi",
            "          if [ -f build.gradle ] || [ -f build.gradle.kts ]; then ./gradlew build; fi",
        ]
    if lang == "Go":
        return [
            "      - uses: actions/setup-go@v5",
            "        with:",
            "          go-version: '1.23'",
            "      - run: go test ./...",
            "      - run: go vet ./...",
        ]
    if lang == "Rust":
        return [
            "      - uses: dtolnay/rust-toolchain@stable",
            "      - run: cargo fmt --all -- --check",
            "      - run: cargo clippy --all-targets --all-features -- -D warnings",
            "      - run: cargo test --all-features",
        ]
    return [
        "      - run: echo \"No language-specific steps detected. Update this workflow manually.\"",
    ]


def _deployment_hint(profile: TechProfile) -> str:
    if "Next.js" in profile.frameworks:
        return "Deploy the built image to ECS/Fly.io/Kubernetes and expose port 3000."
    if "Django" in profile.frameworks or "FastAPI" in profile.frameworks or "Flask" in profile.frameworks:
        return "Run DB migrations during deploy and use a process manager (gunicorn/uvicorn)."
    if "Spring Boot" in profile.frameworks:
        return "Use rolling deploy strategy with health checks on /actuator/health."
    return "Set deployment target and secrets, then replace the placeholder deploy command."


def _github_files(repository: str, profile: TechProfile, include_deploy: bool, include_security: bool) -> Dict[str, str]:
    ci_steps = "\n".join(_ci_steps(profile))
    files: Dict[str, str] = {
        ".github/workflows/ci.yml": f"""name: CI

on:
  pull_request:
  push:
    branches: [main, master]

permissions:
  contents: read

jobs:
  build-test:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
{ci_steps}
""",
    }

    if include_security:
        files[".github/workflows/security.yml"] = """name: Security

on:
  pull_request:
  push:
    branches: [main, master]
  schedule:
    - cron: '0 2 * * 1'

permissions:
  contents: read
  security-events: write

jobs:
  codeql:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: javascript, python, java, go
      - uses: github/codeql-action/analyze@v3

  deps:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aquasecurity/trivy-action@0.24.0
        with:
          scan-type: fs
          format: table
          exit-code: '0'
"""

    if include_deploy:
        files[".github/workflows/cd.yml"] = f"""name: CD

on:
  workflow_dispatch:
  push:
    tags:
      - 'v*'

permissions:
  contents: read
  packages: write
  id-token: write

env:
  REGISTRY: ghcr.io
  IMAGE_NAME: {repository.lower()}

jobs:
  docker:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ${{{{ env.REGISTRY }}}}
          username: ${{{{ github.actor }}}}
          password: ${{{{ secrets.GITHUB_TOKEN }}}}
      - uses: docker/build-push-action@v6
        with:
          context: .
          push: true
          tags: |
            ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}:${{{{ github.ref_name }}}}
            ${{{{ env.REGISTRY }}}}/${{{{ env.IMAGE_NAME }}}}:latest

  deploy:
    needs: docker
    runs-on: ubuntu-latest
    environment: production
    steps:
      - name: Deploy placeholder
        run: |
          echo "Replace this block with your cloud deploy command."
          echo "{_deployment_hint(profile)}"
"""

    return files


def _gitlab_files(repository: str, profile: TechProfile, include_deploy: bool, include_security: bool) -> Dict[str, str]:
    lang = profile.primary_language
    image = "python:3.12"
    install = "pip install -r requirements.txt"
    build = "pytest -q || true"
    if lang in ("JavaScript", "TypeScript"):
        image = "node:20"
        install = "npm ci"
        build = "npm run lint --if-present && npm run build --if-present && npm test --if-present"
    elif lang == "Java":
        image = "maven:3.9-eclipse-temurin-21"
        install = "echo 'maven image ready'"
        build = "mvn -B verify"
    elif lang == "Go":
        image = "golang:1.23"
        install = "go mod download"
        build = "go test ./... && go vet ./..."
    elif lang == "Rust":
        image = "rust:1.82"
        install = "cargo fetch"
        build = "cargo fmt --all -- --check && cargo clippy --all-targets --all-features -- -D warnings && cargo test --all-features"

    deploy_job = ""
    if include_deploy:
        deploy_job = """
deploy:
  stage: deploy
  image: alpine:3.20
  only:
    - tags
  script:
    - echo "Replace this deploy step with your cloud deployment command"
"""

    security_job = ""
    if include_security:
        security_job = """
security_scan:
  stage: security
  image: aquasec/trivy:latest
  script:
    - trivy fs --exit-code 0 --severity HIGH,CRITICAL .
"""

    files = {
        ".gitlab-ci.yml": f"""stages:
  - test
  - security
  - deploy

variables:
  REPOSITORY: "{repository}"

test:
  stage: test
  image: {image}
  script:
    - {install}
    - {build}
{security_job}
{deploy_job}
"""
    }
    return files


def _jenkins_files(profile: TechProfile, include_deploy: bool, include_security: bool) -> Dict[str, str]:
    test_cmd = profile.test_hints[0] if profile.test_hints else "echo 'Add test command'"
    security_stage = ""
    if include_security:
        security_stage = """
    stage('Security') {
      steps {
        sh 'echo "Run SAST/SCA scanner here (Trivy, Snyk, SonarQube)."'
      }
    }
"""
    deploy_stage = ""
    if include_deploy:
        deploy_stage = """
    stage('Deploy') {
      when {
        buildingTag()
      }
      steps {
        sh 'echo "Replace with production deployment script"'
      }
    }
"""

    files = {
        "Jenkinsfile": f"""pipeline {{
  agent any
  options {{
    timestamps()
  }}
  stages {{
    stage('Checkout') {{
      steps {{
        checkout scm
      }}
    }}
    stage('Build and Test') {{
      steps {{
        sh '{test_cmd}'
      }}
    }}
{security_stage}
{deploy_stage}
  }}
}}
"""
    }
    return files


def generate_cicd_files(
    repository: str,
    profile: TechProfile,
    include_deploy: bool,
    include_security: bool,
    ci_provider: Literal["github", "gitlab", "jenkins"],
) -> Dict[str, str]:
    if ci_provider == "gitlab":
        files = _gitlab_files(repository, profile, include_deploy, include_security)
    elif ci_provider == "jenkins":
        files = _jenkins_files(profile, include_deploy, include_security)
    else:
        files = _github_files(repository, profile, include_deploy, include_security)

    secrets_hint = "- Add cloud credentials for deployment (for example `AWS_ROLE_ARN`, `KUBE_CONFIG`, or platform-specific token)."
    if ci_provider == "github":
        secrets_intro = "- `GITHUB_TOKEN` is used automatically by GitHub Actions."
    elif ci_provider == "gitlab":
        secrets_intro = "- Configure GitLab CI/CD variables (`CI_REGISTRY_USER`, deploy credentials, cloud keys)."
    else:
        secrets_intro = "- Configure Jenkins credentials store entries and inject them in your pipeline stages."

    files["cicd/README.md"] = f"""# Generated CI/CD for {repository}

## What was detected
- Primary language: {profile.primary_language}
- Languages: {", ".join(profile.languages)}
- Frameworks: {", ".join(profile.frameworks) if profile.frameworks else "None detected"}
- Package managers: {", ".join(profile.package_managers) if profile.package_managers else "Unknown"}

## Required repository secrets
{secrets_intro}
{secrets_hint}

## Next steps
1. Copy generated files into your repository.
2. Ensure test command(s) are valid.
3. Replace placeholder deploy/security commands with platform-specific commands.
"""

    return files
