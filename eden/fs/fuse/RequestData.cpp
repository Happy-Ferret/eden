/*
 *  Copyright (c) 2016-present, Facebook, Inc.
 *  All rights reserved.
 *
 *  This source code is licensed under the BSD-style license found in the
 *  LICENSE file in the root directory of this source tree. An additional grant
 *  of patent rights can be found in the PATENTS file in the same directory.
 *
 */
#include "RequestData.h"
#include "Dispatcher.h"

#include <folly/experimental/logging/xlog.h>

using namespace folly;
using namespace std::chrono;

namespace facebook {
namespace eden {
namespace fusell {

const std::string RequestData::kKey("fusell");

RequestData::RequestData(
    FuseChannel* channel,
    const fuse_in_header& fuseHeader,
    Dispatcher* dispatcher)
    : channel_(channel), fuseHeader_(fuseHeader), dispatcher_(dispatcher) {}

RequestData::~RequestData() {
  channel_->finishRequest(fuseHeader_);
}

void RequestData::interrupt() {
  // I don't believe that we have to deal with racing to
  // process multiple concurrent interrupt() calls.
  // The potential race is between an interrupt() call
  // and the completion of the request.
  if (!interrupted_) {
    interrupter_.cancel();
    interrupted_ = true;
  }
}

bool RequestData::isFuseRequest() {
  return folly::RequestContext::get()->getContextData(kKey) != nullptr;
}

RequestData& RequestData::get() {
  const auto data = folly::RequestContext::get()->getContextData(kKey);
  if (UNLIKELY(!data)) {
    XLOG(FATAL) << "boom for missing RequestData";
    throw std::runtime_error("no fuse request data set in this context!");
  }
  return *dynamic_cast<RequestData*>(data);
}

RequestData& RequestData::create(
    FuseChannel* channel,
    const fuse_in_header& fuseHeader,
    Dispatcher* dispatcher) {
  folly::RequestContext::get()->setContextData(
      RequestData::kKey,
      std::make_unique<RequestData>(channel, fuseHeader, dispatcher));
  return get();
}

Future<folly::Unit> RequestData::startRequest(
    ThreadLocalEdenStats* stats,
    EdenStats::HistogramPtr histogram) {
  startTime_ = steady_clock::now();
  DCHECK(latencyHistogram_ == nullptr);
  latencyHistogram_ = histogram;
  stats_ = stats;
  return folly::Unit{};
}

void RequestData::finishRequest() {
  const auto now = steady_clock::now();
  const auto now_since_epoch = duration_cast<seconds>(now.time_since_epoch());
  const auto diff = duration_cast<microseconds>(now - startTime_);
  stats_->get()->recordLatency(latencyHistogram_, diff, now_since_epoch);
  latencyHistogram_ = nullptr;
  stats_ = nullptr;
}

fuse_in_header RequestData::stealReq() {
  if (fuseHeader_.opcode == 0) {
    throw std::runtime_error("req_ has been released");
  }
  fuse_in_header res = fuseHeader_;
  fuseHeader_.opcode = 0;
  return res;
}

const fuse_in_header& RequestData::getReq() const {
  if (fuseHeader_.opcode == 0) {
    throw std::runtime_error("req_ has been released");
  }
  return fuseHeader_;
}

Dispatcher* RequestData::getDispatcher() const {
  return dispatcher_;
}

bool RequestData::wasInterrupted() const {
  return interrupted_;
}

void RequestData::replyError(int err) {
  channel_->replyError(stealReq(), err);
}

void RequestData::replyNone() {
  stealReq();
}

void RequestData::systemErrorHandler(const std::system_error& err) {
  int errnum = EIO;
  if (err.code().category() == std::system_category()) {
    errnum = err.code().value();
  }
  XLOG(DBG5) << folly::exceptionStr(err);
  RequestData::get().replyError(errnum);
}

void RequestData::genericErrorHandler(const std::exception& err) {
  XLOG(DBG5) << folly::exceptionStr(err);
  RequestData::get().replyError(EIO);
}
} // namespace fusell
} // namespace eden
} // namespace facebook
