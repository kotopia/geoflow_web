# GIS photo normalized-master and image metadata contract v1

GeoFlow stores a normalized GIS master photo, not the device raw file. The client
extracts metadata first, applies EXIF orientation to pixels, starts at a 1920px long
edge, then reduces JPEG quality and resolution until the result is at most 500KB.
Edited representations follow the same bound.

`extra_data` remains business input. `image_metadata` stores safe EXIF, GPS, source
and normalized dimensions, source orientation, applied rotation/mirroring, normalized
orientation, encoding quality, and target size. Arbitrary vendor EXIF stays in the
tenant database and is not returned by the normal list API.

Replacing a photo preserves the photo id, slot, and order, writes a new immutable S3
replacement object, and clears the old edited representation. Prior S3 objects are
lifecycle-cleanup candidates and are never overwritten.

This preserves future inputs for QField orientation repair, photo-to-feature distance
warnings, slot direction validation, automatic captions, and archive manifests. Those
validations are outside this phase.
