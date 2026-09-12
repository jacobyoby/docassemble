package monitor

import (
	"io"
	"syscall"
	"time"

	"github.com/jacobyoby/docassemble/privacy-diagnostic/internal/nativeguard"
)

const (
	UsageFailure    = 64
	ProtocolFailure = 70
	SinkFailure     = 74
)

// Run is for a dedicated Supervisor event-listener process. Stdout carries
// protocol tokens only; stderr carries fixed-schema records only. No network
// calls, output replay, service changes, or direct file writes are performed.
func Run(args []string) int {
	if len(args) != 0 {
		return UsageFailure
	}
	if syscall.Setrlimit(syscall.RLIMIT_CORE, &syscall.Rlimit{}) != nil || nativeguard.SealDescriptors() != nil {
		return ProtocolFailure
	}
	return run([3]int{0, 1, 2}, 5*time.Second)
}

func run(descriptors [3]int, timeout time.Duration) (code int) {
	var streams []*pipe
	defer func() {
		// Reverse order also restores flags correctly if stdio shares an open file description.
		for i := len(streams) - 1; i >= 0; i-- {
			if streams[i].close() != nil {
				code = SinkFailure
			}
		}
	}()
	for _, fd := range descriptors {
		stream, err := openPipe(fd)
		if err != nil {
			return SinkFailure
		}
		streams = append(streams, stream)
	}
	input, protocol, output := streams[0], streams[1], streams[2]
	if output.write(fixed("monitor", "monitor_ready", "ready"), timeout) != nil {
		return SinkFailure
	}
	var storage [MaxFrame]byte
	defer clear(storage[:])
	for {
		if protocol.write([]byte("READY\n"), timeout) != nil {
			return SinkFailure
		}
		headerBytes, err := readHeader(input, storage[:], timeout)
		if err == io.EOF {
			return 0 // Supervisor closed its input while no event was in flight.
		}
		info, parsed := parseHeader(headerBytes)
		clear(storage[:])
		if err != nil || parsed != nil {
			return protocolFailure(output, timeout)
		}
		_, err = io.ReadFull(input.file, storage[:info.size])
		if err != nil {
			return protocolFailure(output, timeout)
		}
		data, err := eventRecord(info.event, storage[:info.size])
		clear(storage[:])
		if err != nil || input.file.SetReadDeadline(time.Time{}) != nil {
			return protocolFailure(output, timeout)
		}
		if len(data) != 0 && output.write(data, timeout) != nil {
			return SinkFailure // Do not acknowledge undelivered records: Supervisor requeues them.
		}
		if protocol.write([]byte("RESULT 2\nOK"), timeout) != nil {
			return SinkFailure
		}
	}
}

func readHeader(input *pipe, buffer []byte, timeout time.Duration) ([]byte, error) {
	// Idle waits have no deadline. Once a frame starts, one deadline bounds its
	// complete header and payload so a partial sender cannot stall processing.
	if _, err := io.ReadFull(input.file, buffer[:1]); err != nil {
		return nil, err
	}
	if input.file.SetReadDeadline(time.Now().Add(timeout)) != nil {
		return nil, errProtocol
	}
	for size := 1; size <= len(buffer); size++ {
		if buffer[size-1] == '\n' {
			return buffer[:size-1], nil
		}
		if size == len(buffer) {
			break
		}
		if _, err := io.ReadFull(input.file, buffer[size:size+1]); err != nil {
			return nil, errProtocol
		}
	}
	return nil, errProtocol
}

func protocolFailure(output *pipe, timeout time.Duration) int {
	if output.write(fixed("monitor", "protocol_failed", "invalid"), timeout) != nil {
		return SinkFailure
	}
	return ProtocolFailure
}
