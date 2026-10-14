# Native tracker read attribution demonstration

A real loopback request from the plate reader with a declared caller and supplied
`QUIPU_TASK`/`QUIPU_SESSION` sends one ASK query in both versions. Before, only the
caller arrived; the source result preserves caller, task and session plus separate
component/operation declarations. The ASK-false response and query count match.

An explicit caller previously lost precedence to a scoped component declaration.
The source result preserves that explicit caller. Context-free reads do not gain
a crew identity from the component, actor or an inherited non-harness environment.

The focused source suite passes 102 controls including real HTTP and child-process
headers, parent-environment restoration, unchanged write actor/provenance and
plate/count semantics. SDK source controls independently pass 99 library tests
and two built-CLI transport tests. Source tests do not establish scheduled
installation or server visibility of extension headers; native acceptance remains
separate. This is diagnostic attribution, with unchanged request counts.
