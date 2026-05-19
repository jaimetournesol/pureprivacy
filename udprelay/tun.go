//go:build linux

package main

import (
	"fmt"
	"net"
	"os"
	"os/exec"
	"syscall"
	"unsafe"
)

// Linux TUN/TAP ioctl constants — see <linux/if_tun.h>.
const (
	tunDevPath = "/dev/net/tun"
	iffTun     = 0x0001
	iffNoPI    = 0x1000
	tunSetIFF  = 0x400454ca // _IOW('T', 202, int) on Linux/amd64 + arm64
	ifNameLen  = 16
)

type ifreq struct {
	Name  [ifNameLen]byte
	Flags uint16
	pad   [22]byte
}

// openTUN opens /dev/net/tun, attaches it as a TUN interface with the
// requested name, configures the OnionCat /48 IPv6 address on it, and
// brings the link up.  Returns the file handle to read/write raw IP
// packets on.  Requires CAP_NET_ADMIN.
//
// The address is added with prefix length 48 so the kernel installs an
// onlink route for the entire OnionCat /48 — meaning any packet
// destined to *any* OnionCat IPv6 routes here, even though only this
// box's own IPv6 is actually local.
func openTUN(name string, ipv6 net.IP) (*os.File, error) {
	f, err := os.OpenFile(tunDevPath, os.O_RDWR, 0)
	if err != nil {
		return nil, fmt.Errorf("open %s: %w (need /dev/net/tun mounted and CAP_NET_ADMIN)", tunDevPath, err)
	}
	var req ifreq
	copy(req.Name[:], name)
	req.Flags = iffTun | iffNoPI
	if _, _, errno := syscall.Syscall(syscall.SYS_IOCTL, f.Fd(), tunSetIFF, uintptr(unsafe.Pointer(&req))); errno != 0 {
		f.Close()
		return nil, fmt.Errorf("TUNSETIFF on %s: %v", name, errno)
	}
	if out, err := exec.Command("ip", "-6", "addr", "add",
		fmt.Sprintf("%s/48", ipv6.String()), "dev", name).CombinedOutput(); err != nil {
		f.Close()
		return nil, fmt.Errorf("ip -6 addr add %s/48 dev %s: %v: %s", ipv6, name, err, out)
	}
	if out, err := exec.Command("ip", "link", "set", name, "up").CombinedOutput(); err != nil {
		f.Close()
		return nil, fmt.Errorf("ip link set %s up: %v: %s", name, err, out)
	}
	return f, nil
}
