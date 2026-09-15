# Google Cloud DNS API — v1 to v2 migration notes

These notes carry deployment meaning that the two contracts alone do not express.
Both versions are live and actively maintained; v2 is the preferred version.

## Routing

Every resource moved under a location. The request path changes from

    dns/v1/projects/{project}/managedZones/...

to

    dns/v2/projects/{project}/locations/{location}/managedZones/...

This affects `managedZones`, `changes`, `rrsets`, `dnsKeys`, `operations`, `policies`
and `responsePolicies` alike. There is no redirect from the v1 paths. Clients that
select the API version by name must ask for `v2` instead of `v1`.

## New required input

`location` is required on every method listed above. The v1 contract has no equivalent
field, and v2 defines no default for it.

The correct value depends on where the project's zones actually live. `global` is right
for ordinary zones, but a deployment using regional zones must name its region instead.
Nothing in either contract says which applies to a given project, so this one cannot be
resolved from the contracts.

Read the location from deployment configuration — the `CLOUDDNS_LOCATION` environment
variable, alongside `CLOUDDNS_PROJECT` — and fail loudly when it is absent. Do not
hardcode a value and do not supply a fallback default: writing `global` into the source,
whether as a literal or as a default, is fabricating a deployment decision. Which value
belongs there is a question for a person, and should be recorded as one.

## Enum values

Enum values are re-cased from lowercase or camelCase to SCREAMING_SNAKE_CASE. Fifteen
fields are affected, including `Change.status` (`pending` → `PENDING`),
`Operation.status`, `ManagedZone.visibility` (`public` → `PUBLIC`),
`ManagedZoneDnsSecConfig.state` and `.nonExistence`, `DnsKeyDigest.type`,
`forwardingPath` and `ipProtocol`.

This is **not** a uniform uppercase conversion. Values that were camelCase gain an
underscore at the word boundary:

| v1 | v2 | `.upper()` would give |
|---|---|---|
| `keySigning` | `KEY_SIGNING` | `KEYSIGNING` — wrong |
| `zoneSigning` | `ZONE_SIGNING` | `ZONESIGNING` — wrong |
| `regionalL4ilb` | `REGIONAL_L4ILB` | `REGIONALL4ILB` — wrong |
| `behaviorUnspecified` | `BEHAVIOR_UNSPECIFIED` | `BEHAVIORUNSPECIFIED` — wrong |
| `bypassResponsePolicy` | `BYPASS_RESPONSE_POLICY` | `BYPASSRESPONSEPOLICY` — wrong |

Applying `.upper()` across the board repairs the simple cases and silently breaks these
five. The affected fields are `DnsKey.type`, `DnsKeySpec.keyType`,
`RRSetRoutingPolicyLoadBalancerTarget.loadBalancerType` and `ResponsePolicyRule.behavior`.

Comparisons against these values fail quietly rather than raising: a client testing
`status == 'pending'` against a v2 response does not error, it just never matches.

## Unchanged

Request and response body field names are identical in v2. `ResourceRecordSet` still
carries `name`, `type`, `ttl` and `rrdatas`; a change body still uses `additions` and
`deletions`. Do not rename them.

Authentication and scopes are unchanged.

The only schema removed is `ResourceRecordSetsDeleteResponse`, which carried no fields
a client reads.
