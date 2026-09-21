"""DIDL-Lite metadata template used when enqueuing Amazon Music items.

SA_RINCON51463 is the Sonos service descriptor for Amazon Music. item_id is the
catalog path (e.g. "catalog/tracks/B01MQYJR6J/"); uri is the soco:// URI returned
by the music-service search, with '&' already HTML-escaped as '&amp;'.
"""

SONOS_DIDL = (
    '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
    'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/">'
    '<item parentID="DUMMY" restricted="true" id="0fffffff{item_id}">'
    "<dc:title>DUMMY</dc:title>"
    '<res protocolInfo="DUMMY">{uri}</res>'
    "<upnp:class>object.item</upnp:class>"
    '<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
    "SA_RINCON51463_X_#Svc51463-0-Token</desc>"
    "</item></DIDL-Lite>"
)


def track_metadata(item_id: str, uri: str) -> str:
    return SONOS_DIDL.format(item_id=item_id, uri=uri)
