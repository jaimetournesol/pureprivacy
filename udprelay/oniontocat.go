package main

import (
	"crypto/sha256"
	"fmt"
	"net"
	"strings"
)

// onioncatPrefix is the well-known /48 the OnionCat project assigned
// to its overlay network.  PurePrivacy reuses the prefix for two
// reasons: the address space is reserved (ULA, no IANA conflicts) and
// the convention is familiar to anyone who's seen OnionCat docs.
const onioncatPrefix = "fd87:d87e:eb43"

// onioncatIPv6 returns the IPv6 address in fd87:d87e:eb43::/48
// corresponding to a v3 .onion.  v3 onions are 256-bit ed25519
// pubkeys (56-char base32); since they don't fit in the 80 bits
// OnionCat-original allocated below the /48, we derive the suffix
// from SHA-256 of the lowercase onion without the ".onion" tail.
//
// Two boxes given the same .onion will always derive the same IPv6 —
// that's the whole point.  The pairing flow exchanges onions; both
// peers compute the same address for each peer.
func onioncatIPv6(onion string) (net.IP, error) {
	o := strings.ToLower(strings.TrimSpace(onion))
	o = strings.TrimSuffix(o, ".onion")
	if len(o) != 56 {
		return nil, fmt.Errorf("onioncat: %q is not a 56-char v3 onion", o)
	}
	for _, ch := range o {
		// base32 alphabet (RFC 4648 lower)
		if !(ch >= 'a' && ch <= 'z') && !(ch >= '2' && ch <= '7') {
			return nil, fmt.Errorf("onioncat: %q contains non-base32 char %q", o, ch)
		}
	}
	digest := sha256.Sum256([]byte(o))
	ip := make(net.IP, 16)
	ip[0], ip[1] = 0xfd, 0x87
	ip[2], ip[3] = 0xd8, 0x7e
	ip[4], ip[5] = 0xeb, 0x43
	copy(ip[6:], digest[:10])
	return ip, nil
}
