/*
 *  Copyright (c) 2004-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#pragma once

#include <folly/futures/Future.h>

#include "eden/fs/utils/UnixSocket.h"

namespace facebook {
namespace eden {

/**
 * A wrapper around UnixSocket that provides a Future-based API
 * rather than raw callback objects.
 *
 * This class is not thread safe.  It should only be accessed from the
 * EventBase thread that it is attached to.
 */
class FutureUnixSocket : private UnixSocket::ReceiveCallback {
 public:
  using Message = UnixSocket::Message;

  /**
   * Create a new unconnected FutureUnixSocket object.
   *
   * connect() should be called on this socket before any other I/O operations.
   */
  FutureUnixSocket();

  /**
   * Create a FutureUnixSocket object from an existing UnixSocket.
   */
  explicit FutureUnixSocket(UnixSocket::UniquePtr socket);

  /**
   * Create a FutureUnixSocket object from an existing socket descriptor.
   */
  FutureUnixSocket(folly::EventBase* eventBase, folly::File socket);

  ~FutureUnixSocket();
  FutureUnixSocket(FutureUnixSocket&& other) noexcept;
  FutureUnixSocket& operator=(FutureUnixSocket&& other) noexcept;

  /**
   * Connect to a unix socket.
   */
  folly::Future<folly::Unit> connect(
      folly::EventBase* eventBase,
      const folly::SocketAddress& address,
      std::chrono::milliseconds timeout);
  folly::Future<folly::Unit> connect(
      folly::EventBase* eventBase,
      folly::StringPiece path,
      std::chrono::milliseconds timeout);

  /**
   * Get the EventBase that this socket uses for driving I/O operations.
   *
   * All interaction with this FutureUnixSocket object must be done from this
   * EventBase's thread.
   */
  folly::EventBase* getEventBase() const {
    return socket_->getEventBase();
  }

  void setSendTimeout(std::chrono::milliseconds timeout) {
    return socket_->setSendTimeout(timeout);
  }

  /**
   * Returns 'true' if the underlying descriptor is open, or rather,
   * it has not been closed locally.
   */
  explicit operator bool() const {
    return socket_.get() != nullptr;
  }

  /**
   * Get the user ID of the remote peer.
   */
  uid_t getRemoteUID();

  /**
   * Send a message.
   *
   * Returns a Future that will complete when the message has been handed off
   * to the kernel for delivery.
   */
  folly::Future<folly::Unit> send(Message&& msg);
  folly::Future<folly::Unit> send(folly::IOBuf&& data) {
    return send(Message(std::move(data)));
  }
  folly::Future<folly::Unit> send(std::unique_ptr<folly::IOBuf> data) {
    return send(Message(std::move(*data)));
  }

  /**
   * Receive a message.
   *
   * Returns a Future that will be fulfilled when a message is received.
   *
   * receive() may be called multiple times in a row without waiting for
   * earlier receive() calls to be fulfilled.  In this case the futures will be
   * fulfilled as messages are received in the order in which they were
   * created.  (The first receive() call will receive the first message
   * received on the socket, the second receive() call will receive the second
   * message, etc.)
   */
  folly::Future<Message> receive(std::chrono::milliseconds timeout);

 private:
  class SendCallback;
  class ReceiveCallback;
  class ConnectCallback;

  void receiveTimeout();

  void messageReceived(Message&& message) noexcept override;
  void eofReceived() noexcept override;
  void socketClosed() noexcept override;
  void receiveError(const folly::exception_wrapper& ew) noexcept override;

  void failAllPromises(const folly::exception_wrapper& error) noexcept;
  static void failReceiveQueue(
      std::unique_ptr<ReceiveCallback> callback,
      const folly::exception_wrapper& ew);

  UnixSocket::UniquePtr socket_;
  std::unique_ptr<ReceiveCallback> recvQueue_;
  ReceiveCallback* recvQueueTail_{nullptr};
};

} // namespace eden
} // namespace facebook
