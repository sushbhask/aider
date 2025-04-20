import requests
from packaging import version
from packaging.specifiers import SpecifierSet
from treebeardhq import Log



def get_versions_supporting_python38_or_lower(package_name):
    Log.debug("Fetching package data from PyPI", package_name=package_name)
    url = f"https://pypi.org/pypi/{package_name}/json"
    response = requests.get(url)
    if response.status_code != 200:
        Log.error("Failed to fetch data from PyPI", package_name=package_name, status_code=response.status_code)
        print(f"Failed to fetch data for {package_name}")
        return {}

    data = response.json()
    compatible_versions = {}
    Log.debug("Processing releases for package", package_name=package_name, release_count=len(data["releases"]))

    for release, release_data in data["releases"].items():
        if not release_data:  # Skip empty releases
            continue

        requires_python = release_data[0].get("requires_python")

        if requires_python is None:
            compatible_versions[release] = (
                "Unspecified (assumed compatible with Python 3.8 and lower)"
            )
            Log.debug("Release has unspecified Python requirement, assuming compatible", release=release)
        else:
            try:
                spec = SpecifierSet(requires_python)
                if version.parse("3.8") in spec:
                    compatible_versions[release] = (
                        f"Compatible with Python 3.8 (spec: {requires_python})"
                    )
                    Log.debug("Release is compatible with Python 3.8", release=release, requires_python=requires_python)
            except ValueError:
                Log.warn("Invalid requires_python specifier", release=release, requires_python=requires_python)
                print(f"Invalid requires_python specifier for version {release}: {requires_python}")

    Log.info("Completed compatibility analysis", package_name=package_name, compatible_version_count=len(compatible_versions))
    return compatible_versions


def main():
    package_name = "aider-chat"  # Replace with your package name
    Log.info("Starting compatibility check", package_name=package_name)
    compatible_versions = get_versions_supporting_python38_or_lower(package_name)

    print(f"Versions of {package_name} compatible with Python 3.8 or lower:")
    for release, support in sorted(
        compatible_versions.items(), key=lambda x: version.parse(x[0]), reverse=True
    ):
        print(f"{release}: {support}")
    Log.info("Completed displaying compatible versions", package_name=package_name, version_count=len(compatible_versions))


if __name__ == "__main__":
    main()
