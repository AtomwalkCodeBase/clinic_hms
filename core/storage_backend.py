from storages.backends.s3boto3 import S3Boto3Storage


class mediaStorage(S3Boto3Storage):
    location = "media"
    file_overwrite = False
    default_acl = None

    def get_available_name(self, name, max_length=None):
        return name
