# Transmission tower and line segment

This is the neutral reusable shape for `transmission_line_segment`; it is not a
Minnesota placement. The two named connector empties are geometric attachment
points only and do not describe a circuit or energisation.

Build the handoff artifacts with Blender:

```sh
blender --background --python transmission_line_segment.blender.py -- /tmp/flux-assets
```

Handoff must contain `transmission_line_segment.glb` and its 512px preview
beside `transmission_line_segment.meta.json`. Do not commit the generated GLB:
2WKG-374 owns binary storage, import, placement, and accepted-artifact binding.
