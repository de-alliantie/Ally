import os
from pathlib import Path

import httpx
from msal import ConfidentialClientApplication


class SharePointUtility:
    """Utility class for interacting with SharePoint through the Microsoft Graph API."""

    def __init__(self):
        """Initialize SharePointUtility."""

        self.sitename = None
        self.site_id = None
        self.client = httpx.Client()
        self.access_token = None

    def connect(self, sitename, sharepoint_url, tenant_id, client_id, private_key, private_key_thumbprint) -> str:
        """Connect to SharePoint, save the access token internally and init the httpx client with the access token."""

        self.sitename = sitename
        self.sharepoint_url = sharepoint_url

        app = ConfidentialClientApplication(
            client_id,
            authority=f"https://login.microsoftonline.com/{tenant_id}",
            client_credential={"thumbprint": private_key_thumbprint, "private_key": private_key},
        )

        scope = "https://graph.microsoft.com/.default"

        result = app.acquire_token_for_client(scopes=[scope])
        if not result or "access_token" not in result:
            raise RuntimeError(f"Failed to acquire token: {result}")
        self.access_token = result["access_token"]

        self.client = httpx.Client(headers={"Authorization": f"Bearer {self.access_token}"})

        self.site_id = self.get_site_id(self.sitename)

        return self.access_token

    def get_site_id(self, sitename: str) -> str:
        """Get the SharePoint site ID for a given site name."""

        site_url = f"{self.sharepoint_url.split('https://')[1]}:/sites/{sitename}:"
        endpoint = f"https://graph.microsoft.com/v1.0/sites/{site_url}"

        resp = self.client.get(endpoint)
        resp.raise_for_status()
        data = resp.json()

        site_id = data["id"]

        print(f"Site ID: {site_id}")

        return site_id

    def list_drives(self) -> list:
        """List all drives (document libraries) in a SharePoint site."""

        endpoint = f"https://graph.microsoft.com/v1.0/sites/{self.site_id}/drives"

        resp = self.client.get(endpoint)
        resp.raise_for_status()
        data = resp.json()
        drives = data["value"]

        for drive in drives:
            print("Drive ID:", drive["id"])
            print("Drive Name:", drive["name"])
            print("Drive Web URL:", drive["webUrl"])
            print()

        return drives

    def get_drive_id_by_name(self, name: str) -> str | None:
        """Get the drive ID from its name."""
        drives = self.list_drives()

        # Save the drive ID
        try:
            drive_id = next((drive["id"] for drive in drives if drive["name"] == name))
        except StopIteration:
            print(f"Drive not found: {name}")
            drive_id = None

        return drive_id

    def list_content_in_drive(self, drive_id: str, folder_path: str) -> list:
        """List all content in a specific folder of a SharePoint document library."""

        endpoint = (
            f"https://graph.microsoft.com/v1.0/sites/{self.site_id}/drives/{drive_id}/root:/{folder_path}:/children"
        )
        resp = self.client.get(endpoint)
        resp.raise_for_status()
        data = resp.json()

        contents = data["value"]

        for content in contents:

            # Check if it is a folder or a file
            if content.get("folder") is not None:
                print("Type: Folder")
                print("Folder ID:", content["id"])
                print("Folder Name:", content["name"])
                print("Folder Web URL:", content["webUrl"])
                content["type"] = "folder"

            else:
                print("Type: File")
                print("File ID:", content["id"])
                print("File Name:", content["name"])
                print("File Web URL:", content["webUrl"])
                content["type"] = "file"

            print()

        return contents

    def get_file_id_by_path(self, drive_id: str, file_path: str) -> str:
        """Get the file ID from its path."""

        url = f"https://graph.microsoft.com/v1.0/" f"sites/{self.site_id}/drives/{drive_id}/root:/{file_path}"

        resp = self.client.get(url)
        resp.raise_for_status()
        data = resp.json()

        return data["id"]

    def download_file_by_id(self, drive_id: str, item_id: str, output_path: str):
        """Downloads a file from SharePoint by its ID."""

        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"

        with self.client.stream("GET", url, follow_redirects=True) as r:
            r.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in r.iter_bytes():
                    if chunk:
                        f.write(chunk)
            print(f"Downloaded to: {output_path}")

    def download_file_by_path(self, drive_id: str, file_path: str, output_path: str):
        """Downloads a file from SharePoint by its path."""

        file_id = self.get_file_id_by_path(drive_id, file_path)

        filename = file_path.split("/")[-1]

        if file_id:
            self.download_file_by_id(drive_id, file_id, f"{output_path}/{filename}")

    def get_folder_id_by_path(self, drive_id: str, folder_path: str) -> str:
        """Get the folder ID from its path."""
        url = f"https://graph.microsoft.com/v1.0/" f"sites/{self.site_id}/drives/{drive_id}/root:/{folder_path}"

        resp = self.client.get(url)
        resp.raise_for_status()
        data = resp.json()

        return data["id"]

    def ensure_folder_exists(self, drive_id: str, folder_path: str):
        """Ensure the folder (and its parents) exist in the SharePoint document library.

        Creates them if needed.
        """

        parent_path = ""
        for part in folder_path.strip("/").split("/"):
            current_path = f"{parent_path}/{part}" if parent_path else part
            try:
                self.get_folder_id_by_path(drive_id, current_path)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    # Correct endpoint for root
                    if parent_path:
                        endpoint = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{parent_path}:/children"
                    else:
                        endpoint = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                    body = {"name": part, "folder": {}, "conflictBehavior": "replace"}
                    resp = self.client.post(endpoint, json=body)
                    resp.raise_for_status()
                else:
                    raise
            parent_path = current_path

    def upload_file(self, drive_id: str, folder_path: str, local_file_path: str):
        """Uploads a file to a SharePoint document library.

        Creates the folder if it does not exist.
        """
        file_path = Path(local_file_path)

        # Ensure the folder exists (create if needed)
        self.ensure_folder_exists(drive_id, folder_path)
        folder_id = self.get_folder_id_by_path(drive_id, folder_path)

        url = f"https://graph.microsoft.com/v1.0/" f"drives/{drive_id}/items/{folder_id}:/{file_path.name}:/content"

        headers = {
            "Content-Type": "application/octet-stream",
        }

        with open(file_path, "rb") as f:
            resp = self.client.put(url, headers=headers, content=f.read())
            resp.raise_for_status()
            return resp.json()


if __name__ == "__main__":

    ###### Example usage ######

    # 1: Connect to SharePoint

    SITENAME = "DCC-python"

    TENANT_ID = os.environ["TENANT_ID"]
    SHAREPOINT_URL = os.environ["SHAREPOINT_URL"]
    SPO_APPONLY_CERT_DCC_PYTHON_CLIENT_ID = os.environ["SPO_APPONLY_CERT_DCC_PYTHON_CLIENT_ID"]
    SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY = os.environ["SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY"]
    SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY_THUMBPRINT = os.environ[
        "SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY_THUMBPRINT"
    ]

    sp = SharePointUtility()
    sp.connect(
        sitename=SITENAME,
        sharepoint_url=SHAREPOINT_URL,
        tenant_id=TENANT_ID,
        client_id=SPO_APPONLY_CERT_DCC_PYTHON_CLIENT_ID,
        private_key=SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY,
        private_key_thumbprint=SPO_APPONLY_CERT_DCC_PYTHON_PRIVATE_KEY_THUMBPRINT,
    )

    # 2: Find the drive you want to access
    DATA_SCIENCE_OPS_DRIVE_ID = sp.get_drive_id_by_name(name="Data Science OPS")

    if DATA_SCIENCE_OPS_DRIVE_ID is not None:

        # 3: Download a file
        sp.download_file_by_path(
            drive_id=DATA_SCIENCE_OPS_DRIVE_ID,
            file_path="Full/path/to/file/including/filename.txt",
            output_path="src/scheduled_runs",
        )

        # 4: Upload a file
        response = sp.upload_file(
            drive_id=DATA_SCIENCE_OPS_DRIVE_ID,
            folder_path="Klantenservice-Ally/Test/Gesprekken/placehere",
            local_file_path="testfile.txt",
        )
        print(response)

        # (Optional) List the content of a drivefolder
        files = sp.list_content_in_drive(drive_id=DATA_SCIENCE_OPS_DRIVE_ID, folder_path="Klantenservice-Ally")
